"""Client profiles: everything that varies by client or project, in YAML.

    config/profiles/default.yaml   used when no profile is given
    config/profiles/<client>.yaml  `extends: default` and overrides only what differs

Lists in a child profile replace the parent's list unless the key ends in `_extra`,
in which case they are appended (e.g. `id_patterns_extra`).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel

PROFILES_DIR = Path("config/profiles")


class SheetOverride(BaseModel):
    header_row: Optional[int] = None       # force header row (1-based)
    id_column: Optional[str] = None
    scenario_column: Optional[str] = None
    scenario: Optional[str] = None         # assign the whole sheet to this scenario label
    skip: bool = False


class ClientProfile(BaseModel):
    name: str = "default"
    # --- IDs -----------------------------------------------------------
    id_patterns: list[str] = []
    id_column_names: list[str] = []
    # --- scenarios -----------------------------------------------------
    scenario_patterns: list[str] = []          # must define groups: kind, ord, name
    scenario_column_names: list[str] = []
    shared_labels: list[str] = []
    stop_words: list[str] = []                 # ignored when building scenario keywords
    scenario_aliases: dict[str, list[str]] = {}   # canonical name -> other spellings
    segment_mode: str = "auto"                 # auto | whole_file | per_row
    keyword_assignment: bool = True
    # --- documents ------------------------------------------------------
    brs_markers: list[str] = []
    brd_markers: list[str] = []
    doc_id_patterns: list[str] = []
    parent_id_patterns: list[str] = []
    # --- cleaning -------------------------------------------------------
    skip_sheet_patterns: list[str] = []
    skip_hidden_sheets: bool = True
    furniture_min_pages: float = 0.5           # a line repeated on >= this share of pages is header/footer
    # --- pipeline -------------------------------------------------------
    cleaners: list[str] = []
    scenario_finders: list[str] = []
    assigner: str = "explicit_then_keyword"
    conflict_detectors: list[str] = []
    conflict_similarity_threshold: float = 0.85
    # --- per sheet / per file overrides --------------------------------
    sheets: dict[str, SheetOverride] = {}

    # compiled helpers ---------------------------------------------------
    def id_regexes(self) -> list[re.Pattern]:
        return [re.compile(p) for p in self.id_patterns]

    def scenario_regexes(self) -> list[re.Pattern]:
        return [re.compile(p, re.I) for p in self.scenario_patterns]

    def is_id(self, value: str) -> bool:
        v = value.strip()
        return bool(v) and len(v) <= 40 and any(r.fullmatch(v) for r in self.id_regexes())

    def leading_id(self, text: str) -> Optional[str]:
        t = text.strip()
        for r in self.id_regexes():
            m = r.match(t)
            if m and (len(t) == m.end() or not t[m.end()].isalnum()):
                return m.group(0)
        return None

    def sheet_override(self, sheet: str) -> SheetOverride:
        for pat, ov in self.sheets.items():
            if re.fullmatch(pat, sheet, re.I) or pat == sheet:
                return ov
        return SheetOverride()


def _merge(parent: dict, child: dict) -> dict:
    out = dict(parent)
    for k, v in child.items():
        if k.endswith("_extra"):
            base = k[: -len("_extra")]
            out[base] = list(out.get(base, [])) + list(v or [])
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_raw(name_or_path: str, seen: set[str]) -> dict[str, Any]:
    p = Path(name_or_path)
    if not p.suffix:
        p = PROFILES_DIR / f"{name_or_path}.yaml"
    if str(p) in seen:
        raise ValueError(f"Profile inheritance loop at {p}")
    seen.add(str(p))
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    parent = raw.pop("extends", None)
    if parent:
        return _merge(_load_raw(parent, seen), raw)
    return raw


def load_profile(name_or_path: str | None = None) -> ClientProfile:
    raw = _load_raw(name_or_path or "default", set())
    raw.setdefault("name", Path(name_or_path or "default").stem)
    return ClientProfile.model_validate(raw)
