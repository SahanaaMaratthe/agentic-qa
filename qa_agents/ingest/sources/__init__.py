"""Source plug-ins: fetch input files from wherever they live into a local folder.

A source implements:
    priority: int                       lower = asked first (local is last)
    can_handle(uri) -> bool
    fetch(uri, dest_dir) -> list[(local_path, display_name)]
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

SUPPORTED_EXTS = {".xlsx", ".xlsm", ".pdf", ".docx", ".docm", ".md", ".txt", ".markdown", ".xls", ".doc"}


class Source:
    plugin_name = "base"
    priority = 50

    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}

    def can_handle(self, uri: str) -> bool:
        raise NotImplementedError

    def fetch(self, uri: str, dest: Path) -> list[tuple[Path, str]]:
        raise NotImplementedError

    # helpers --------------------------------------------------------------
    def static_token(self) -> str | None:
        """token_env / token_command auth modes shared by all cloud sources."""
        s = self.settings
        if s.get("auth") == "token_env":
            tok = os.environ.get(s.get("token_env", ""), "")
            if not tok:
                raise RuntimeError(f"Environment variable {s.get('token_env')} is empty")
            return tok
        if s.get("auth") == "token_command":
            out = subprocess.run(shlex.split(s["token_command"]), capture_output=True, text=True, check=True)
            return out.stdout.strip()
        return None


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")
    return name[:150] or "file"


def unique_path(dest: Path, name: str) -> Path:
    p = dest / safe_name(name)
    i = 2
    while p.exists():
        p = dest / f"{p.stem} ({i}){p.suffix}"
        i += 1
    return p
