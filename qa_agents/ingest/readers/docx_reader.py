"""Word (.docx) reader: headings by style (or short all-bold lines), list items by
numbering/style, tables with merged cells (horizontal merges de-duplicated,
vertical merges repeated so multi-row records can be grouped later)."""
from __future__ import annotations

import re
from pathlib import Path

from ..model import Block, IngestedDocument, SourceRef
from ..profile import ClientProfile
from ..registry import register
from ..tables import norm, table_from_rows
from . import Reader


@register("reader", "docx")
class DocxReader(Reader):
    extensions = (".docx", ".docm")

    def read(self, path: Path, profile: ClientProfile, display_name: str | None = None) -> IngestedDocument:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        name = display_name or path.name
        d = docx.Document(str(path))
        doc = IngestedDocument(name=name, path=str(path), format="docx")
        try:
            doc.title = norm(d.core_properties.title or "")
        except Exception:  # noqa: BLE001
            pass
        heading_path: list[str] = []
        table_no = 0
        for el in d.element.body.iterchildren():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "p":
                p = Paragraph(el, d)
                text = norm(p.text)
                if not text:
                    continue
                style = (p.style.name if p.style is not None else "") or ""
                lvl = _heading_level(p, style, text)
                if lvl:
                    heading_path = heading_path[: lvl - 1] + [text]
                    doc.blocks.append(Block(kind="heading", text=text, level=lvl,
                                            ref=SourceRef(file=name, section=" > ".join(heading_path))))
                    if lvl == 1 and not doc.title and style.lower() == "title":
                        doc.title = text
                    continue
                is_list = el.pPr is not None and el.pPr.numPr is not None or "list" in style.lower()
                doc.blocks.append(Block(kind="list_item" if is_list else "paragraph", text=text,
                                        ref=SourceRef(file=name, section=" > ".join(heading_path))))
            elif tag == "tbl":
                table_no += 1
                t = Table(el, d)
                raw, refs = [], []
                n_cols = len(t.columns)
                for ri in range(len(t.rows)):
                    row, seen = [], set()
                    for ci in range(n_cols):
                        try:
                            cell = t.cell(ri, ci)
                        except IndexError:
                            row.append("")
                            continue
                        key = id(cell._tc)
                        row.append("" if key in seen else cell.text)
                        seen.add(key)
                    raw.append(row)
                    refs.append(SourceRef(file=name, section=" > ".join(heading_path) or f"table {table_no}", row=ri))
                headers, rows = table_from_rows(raw, refs, True)
                doc.blocks.append(Block(kind="table", headers=headers, rows=rows,
                                        ref=SourceRef(file=name, section=" > ".join(heading_path) or f"table {table_no}")))
        return doc


def _heading_level(p, style: str, text: str) -> int:
    s = style.lower()
    if s == "title":
        return 1
    m = re.match(r"heading\s*(\d)", s)
    if m:
        return int(m.group(1)) + (0 if s.startswith("heading") else 0)
    runs = [r for r in p.runs if r.text.strip()]
    if runs and all(r.bold for r in runs) and len(text) < 90 and not text.endswith((".", ";", ",")):
        return 3
    return 0
