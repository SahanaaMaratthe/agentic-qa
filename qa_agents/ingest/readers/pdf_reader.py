"""PDF reader (typed PDFs; scanned pages are detected and reported).

* tables via pdfplumber (wrapped cells kept together)
* headings by font size / bold numbered lines
* paragraphs and list items by line spacing and indentation (bullets are often
  drawn as shapes, not characters, so they can't be relied on)
Page headers/footers and tables split across pages are handled by cleaners.
"""
from __future__ import annotations

import logging
import re
import statistics
from collections import Counter
from pathlib import Path

from ..model import Block, IngestedDocument, SourceRef
from ..profile import ClientProfile
from ..registry import register
from ..tables import table_from_rows
from . import Reader

for _n in ("pdfminer", "pdfplumber"):
    logging.getLogger(_n).setLevel(logging.ERROR)

LIST_MARKER = re.compile(r"^(\d{1,2}[.)]|[a-z][.)]|[•\-–▪●○■•])\s+")
NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\.?\s+\S")


@register("reader", "pdf")
class PdfReader(Reader):
    extensions = (".pdf",)
    min_chars_per_page = 40        # below this a page is considered scanned / image-only

    def read(self, path: Path, profile: ClientProfile, display_name: str | None = None) -> IngestedDocument:
        import pdfplumber

        name = display_name or path.name
        doc = IngestedDocument(name=name, path=str(path), format="pdf")
        pages_lines, pages_tables, page_heights, sizes = [], [], [], Counter()
        scanned = []
        with pdfplumber.open(path) as pdf:
            for pno, page in enumerate(pdf.pages, 1):
                tables = page.find_tables()
                bboxes = [t.bbox for t in tables]
                lines = []
                for ln in page.extract_text_lines(return_chars=True):
                    mid = (ln["top"] + ln["bottom"]) / 2
                    if any(b[1] - 1 <= mid <= b[3] + 1 and b[0] - 1 <= ln["x0"] <= b[2] + 1 for b in bboxes):
                        continue
                    chars = [c for c in ln["chars"] if c["text"].strip()]
                    if not chars:
                        continue
                    size = round(statistics.median(c["size"] for c in chars), 1)
                    bold_share = sum("Bold" in c["fontname"] or "Black" in c["fontname"] for c in chars) / len(chars)
                    lines.append({"text": ln["text"].strip(), "x0": ln["x0"], "top": ln["top"], "bottom": ln["bottom"],
                                  "size": size, "bold": bold_share > 0.8, "first_bold": "Bold" in chars[0]["fontname"],
                                  "page": pno, "page_h": page.height})
                    sizes[size] += len(chars)
                pages_lines.append(lines)
                pages_tables.append([(t.bbox, t.extract()) for t in tables])
                page_heights.append(page.height)
                if len(page.chars) < self.min_chars_per_page:
                    scanned.append(pno)

        if scanned:
            doc.warnings.append(
                f"{name}: page(s) {', '.join(map(str, scanned))} contain almost no selectable text and look scanned. "
                f"Their content was NOT read. Use a typed PDF, or enable OCR (see docs/EXTENDING.md).")
        body = sizes.most_common(1)[0][0] if sizes else 11.0
        heading_sizes = sorted({ln["size"] for pl in pages_lines for ln in pl
                                if ln["size"] >= body + 0.4 and ln["bold"]}, reverse=True)
        level_of = {s: i + 1 for i, s in enumerate(heading_sizes)}
        margin = min((ln["x0"] for pl in pages_lines for ln in pl), default=0)

        for pno, (lines, tables) in enumerate(zip(pages_lines, pages_tables), 1):
            items = [("line", ln["top"], ln) for ln in lines] + [("table", t[0][1], t) for t in tables]
            items.sort(key=lambda x: x[1])
            para: list[dict] = []
            gaps = [b["top"] - a["top"] for a, b in zip(lines, lines[1:]) if 0 < b["top"] - a["top"] < 3 * body]
            line_gap = statistics.median(gaps) if gaps else body * 1.5

            def flush():
                if not para:
                    return
                text = " ".join(p["text"] for p in para)
                text = re.sub(r"(\w)- (\w)", r"\1-\2", text)
                kind = "list_item" if (para[0]["x0"] > margin + 4 or LIST_MARKER.match(text)) else "paragraph"
                doc.blocks.append(Block(kind=kind, text=text, ref=SourceRef(file=name, page=pno),
                                        meta={"top": para[0]["top"], "bottom": para[-1]["bottom"],
                                              "page_h": para[0]["page_h"], "lead_bold": para[0]["first_bold"]}))
                para.clear()

            for kind, _, obj in items:
                if kind == "table":
                    flush()
                    bbox, raw = obj
                    refs = [SourceRef(file=name, page=pno, row=i) for i in range(len(raw))]
                    headers, rows = table_from_rows([[c or "" for c in r] for r in raw], refs, True)
                    doc.blocks.append(Block(kind="table", headers=headers, rows=rows, ref=SourceRef(file=name, page=pno),
                                            meta={"top": bbox[1], "bottom": bbox[3], "page_h": page_heights[pno - 1],
                                                  "raw_header": raw[0] if raw else []}))
                    continue
                ln = obj
                is_heading = ln["bold"] and (ln["size"] in level_of or
                                             (NUMBERED_HEADING.match(ln["text"]) and len(ln["text"]) < 90
                                              and ln["size"] >= body))
                if is_heading:
                    flush()
                    lvl = level_of.get(ln["size"], len(heading_sizes) + 1)
                    doc.blocks.append(Block(kind="heading", text=ln["text"], level=lvl, ref=SourceRef(file=name, page=pno),
                                            meta={"top": ln["top"], "bottom": ln["bottom"], "page_h": ln["page_h"]}))
                    continue
                prev = para[-1] if para else None
                new_block = (prev is None or ln["top"] - prev["top"] > line_gap * 1.12
                             or LIST_MARKER.match(ln["text"]) or ln["size"] != prev["size"])
                if new_block:
                    flush()
                para.append(ln)
            flush()

        if heading_sizes and pages_lines and pages_lines[0]:
            top = max(pages_lines[0], key=lambda l: l["size"])
            doc.title = top["text"]
        return doc
