"""Plain text / Markdown reader (also used for the original short use-case .md files)."""
from __future__ import annotations

import re
from pathlib import Path

from ..model import Block, IngestedDocument, SourceRef
from ..profile import ClientProfile
from ..registry import register
from ..tables import table_from_rows
from . import Reader


@register("reader", "text")
class TextReader(Reader):
    extensions = (".md", ".txt", ".markdown")

    def read(self, path: Path, profile: ClientProfile, display_name: str | None = None) -> IngestedDocument:
        name = display_name or path.name
        doc = IngestedDocument(name=name, path=str(path), format="text")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        para: list[str] = []
        table: list[list[str]] = []
        table_start = 0

        def flush_para(n):
            if para:
                doc.blocks.append(Block(kind="paragraph", text=" ".join(para), ref=SourceRef(file=name, row=n)))
                para.clear()

        def flush_table():
            nonlocal table
            if table:
                rows = [r for r in table if not all(re.fullmatch(r":?-{2,}:?", c.strip()) for c in r if c.strip())]
                refs = [SourceRef(file=name, row=table_start + i) for i in range(len(rows))]
                headers, trows = table_from_rows(rows, refs, True)
                doc.blocks.append(Block(kind="table", headers=headers, rows=trows, ref=SourceRef(file=name, row=table_start)))
                table = []

        for n, raw in enumerate(lines, 1):
            line = raw.rstrip()
            if line.strip().startswith("|") and line.strip().endswith("|"):
                flush_para(n)
                if not table:
                    table_start = n
                table.append([c.strip() for c in line.strip().strip("|").split("|")])
                continue
            flush_table()
            m = re.match(r"^(#{1,6})\s+(.*)", line)
            if m:
                flush_para(n)
                doc.blocks.append(Block(kind="heading", text=m.group(2).strip(), level=len(m.group(1)),
                                        ref=SourceRef(file=name, row=n)))
                if not doc.title:
                    doc.title = m.group(2).strip()
                continue
            if re.match(r"^\s*([-*+]|\d+[.)])\s+", line):
                flush_para(n)
                doc.blocks.append(Block(kind="list_item", text=re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", line),
                                        ref=SourceRef(file=name, row=n)))
                continue
            if not line.strip():
                flush_para(n)
                continue
            para.append(line.strip())
        flush_para(len(lines))
        flush_table()
        return doc
