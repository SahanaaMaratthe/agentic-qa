"""Plug-in registry.

Six kinds of plug-in make up the ingest pipeline:

    source            fetches files (local, Google Drive, SharePoint ...)
    reader            turns one file format into an IngestedDocument
    cleaner           removes noise from a document (page footers, split tables ...)
    scenario_finder   discovers scenario mentions in a document
    assigner          assigns each item to scenario(s)
    conflict_detector finds contradictions between items / documents

Register a plug-in with the decorator:

    from qa_agents.ingest.registry import register

    @register("reader", "csv")
    class CsvReader(Reader):
        ...

Plug-ins living outside this repository are loaded from
  * settings.yaml -> ingest.plugins: [my_package.my_module, ...]
  * Python entry points in the group "agentic_qa.plugins"
Importing the module is enough: its decorators register the classes.
"""
from __future__ import annotations

import importlib
import logging
from importlib import metadata

log = logging.getLogger(__name__)

KINDS = ("source", "reader", "cleaner", "scenario_finder", "assigner", "conflict_detector")
_REGISTRY: dict[str, dict[str, type]] = {k: {} for k in KINDS}
_loaded_external = False


def register(kind: str, name: str):
    if kind not in _REGISTRY:
        raise ValueError(f"Unknown plug-in kind '{kind}'. Kinds: {KINDS}")

    def deco(cls):
        cls.plugin_name = name
        _REGISTRY[kind][name] = cls
        return cls

    return deco


def get(kind: str, name: str) -> type:
    try:
        return _REGISTRY[kind][name]
    except KeyError:
        raise KeyError(f"No {kind} plug-in named '{name}'. Available: {sorted(_REGISTRY[kind])}") from None


def available(kind: str) -> dict[str, type]:
    return dict(_REGISTRY[kind])


def load_builtin() -> None:
    # importing the modules registers the built-in plug-ins
    from . import cleaners, conflicts, scenarios  # noqa: F401
    from .readers import docx_reader, pdf_reader, text_reader, xlsx_reader  # noqa: F401
    from .sources import gdrive, local, sharepoint  # noqa: F401


def load_external(modules: list[str] | None = None) -> None:
    global _loaded_external
    for m in modules or []:
        importlib.import_module(m)
    if _loaded_external:
        return
    try:
        eps = metadata.entry_points(group="agentic_qa.plugins")
    except TypeError:  # very old Python
        eps = metadata.entry_points().get("agentic_qa.plugins", [])
    for ep in eps:
        try:
            ep.load()
        except Exception as e:  # noqa: BLE001 - a broken third-party plug-in must not stop the run
            log.warning("Could not load plug-in %s: %s", ep.name, e)
    _loaded_external = True
