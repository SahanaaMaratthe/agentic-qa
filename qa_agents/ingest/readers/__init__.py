"""Reader plug-ins: one per file format. Each turns a file into an IngestedDocument."""
from __future__ import annotations

from pathlib import Path

from ..model import IngestedDocument
from ..profile import ClientProfile

LEGACY_FORMATS = {
    ".xls": "Old Excel 97-2003 format (.xls). Open it in Excel and use File > Save As > Excel Workbook (.xlsx).",
    ".doc": "Old Word 97-2003 format (.doc). Open it in Word and use File > Save As > Word Document (.docx).",
    ".ppt": "PowerPoint files are not supported as requirement sources.",
}


class Reader:
    """Base class. Set `extensions`, implement `read`. Register with @register("reader", "<name>")."""

    plugin_name = "base"
    extensions: tuple[str, ...] = ()

    def can_read(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def read(self, path: Path, profile: ClientProfile, display_name: str | None = None) -> IngestedDocument:
        raise NotImplementedError
