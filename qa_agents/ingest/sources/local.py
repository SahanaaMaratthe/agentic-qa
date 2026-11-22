"""Local files and folders (also what the web page's upload button uses)."""
from __future__ import annotations

import glob
from pathlib import Path

from ..registry import register
from . import SUPPORTED_EXTS, Source


@register("source", "local")
class LocalSource(Source):
    priority = 100

    def can_handle(self, uri: str) -> bool:
        return Path(uri).expanduser().exists() or any(c in uri for c in "*?[") and bool(glob.glob(uri))

    def fetch(self, uri: str, dest: Path) -> list[tuple[Path, str]]:
        p = Path(uri).expanduser()
        if p.is_file():
            return [(p, p.name)]
        if p.is_dir():
            pattern = "**/*" if self.settings.get("recursive", True) else "*"
            files = [f for f in sorted(p.glob(pattern))
                     if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS and not f.name.startswith(("~$", "."))]
            return [(f, str(f.relative_to(p))) for f in files]
        return [(Path(f), Path(f).name) for f in sorted(glob.glob(uri)) if Path(f).suffix.lower() in SUPPORTED_EXTS]
