"""Excel (.xlsx / .xlsm) reader.

Handles: header rows that are not row 1, title / section rows (merged banners),
several tables on one sheet, vertically merged cells (filled down so multi-row
records can be grouped later), formulas (saved value used; never-calculated
formulas dropped with a warning), hidden sheets (flagged for the skip cleaner).
"""
from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

from ..model import Block, IngestedDocument, SourceRef
from ..profile import ClientProfile
from ..registry import register
from ..tables import norm, table_from_rows
from . import Reader


@register("reader", "xlsx")
class XlsxReader(Reader):
    extensions = (".xlsx", ".xlsm")

    def read(self, path: Path, profile: ClientProfile, display_name: str | None = None) -> IngestedDocument:
        name = display_name or path.name
        wb = openpyxl.load_workbook(path, data_only=False)
        wb_vals = openpyxl.load_workbook(path, data_only=True)
        doc = IngestedDocument(name=name, path=str(path), format="xlsx")
        dropped_formulas = 0

        for ws in wb.worksheets:
            ws_vals = wb_vals[ws.title]
            hidden = ws.sheet_state != "visible"
            override = profile.sheet_override(ws.title)
            sheet_meta = {"sheet_hidden": hidden, "sheet_override_skip": override.skip}

            # vertical merges are filled down; horizontal-only merges (banners) are left as one cell
            fill: dict[tuple[int, int], object] = {}
            for rng in ws.merged_cells.ranges:
                if rng.max_row > rng.min_row:
                    top = ws_vals.cell(rng.min_row, rng.min_col).value
                    if top is None:
                        top = ws.cell(rng.min_row, rng.min_col).value
                    for r in range(rng.min_row, rng.max_row + 1):
                        for c in range(rng.min_col, rng.max_col + 1):
                            fill[(r, c)] = top

            grid: list[tuple[int, list[str]]] = []
            for r in range(1, ws.max_row + 1):
                vals = []
                for c in range(1, ws.max_column + 1):
                    raw = fill.get((r, c), ws.cell(r, c).value)
                    if isinstance(raw, str) and raw.startswith("="):
                        cached = ws_vals.cell(r, c).value
                        if cached is None:
                            dropped_formulas += 1
                            raw = None
                        else:
                            raw = cached
                    vals.append("" if raw is None else norm(raw) if not isinstance(raw, str) else raw.strip())
                grid.append((r, vals))

            doc.blocks.append(Block(kind="heading", text=ws.title, level=1,
                                    ref=SourceRef(file=name, sheet=ws.title), meta={**sheet_meta, "sheet_title": True}))
            self._sheet_to_blocks(doc, name, ws.title, grid, override.header_row, sheet_meta)

        if dropped_formulas:
            doc.warnings.append(f"{name}: {dropped_formulas} formula cell(s) had no saved value (the file was never "
                                f"recalculated in Excel) and were ignored.")
        return doc

    def _sheet_to_blocks(self, doc, name, sheet, grid, forced_header, sheet_meta):
        table_rows: list[list[str]] = []
        table_refs: list[SourceRef] = []
        table_cols: list[int] = []
        headings_seen = 0

        def close():
            nonlocal table_rows, table_refs
            if table_rows:
                first_is_header = not (len(table_rows) and _looks_like_data(table_rows[0]))
                headers, rows = table_from_rows(table_rows, table_refs, first_is_header)
                if rows or headers:
                    doc.blocks.append(Block(kind="table", headers=headers, rows=rows,
                                            ref=table_refs[0], meta={**sheet_meta, "columns": table_cols}))
            table_rows, table_refs = [], []

        for r, vals in grid:
            filled = [(i, v) for i, v in enumerate(vals) if v]
            if forced_header and r < forced_header:
                if filled:
                    doc.blocks.append(Block(kind="paragraph", text=" ".join(v for _, v in filled),
                                            ref=SourceRef(file=name, sheet=sheet, row=r), meta=sheet_meta))
                continue
            if not filled:
                close()
                continue
            in_table = bool(table_rows)
            if len(filled) == 1 and not (in_table and filled[0][0] != table_cols[0]):
                # a lone cell: banner title / section heading (or a lone first-column value)
                close()
                headings_seen += 1
                doc.blocks.append(Block(kind="heading", text=filled[0][1], level=2 if headings_seen == 1 else 3,
                                        ref=SourceRef(file=name, sheet=sheet, row=r), meta=sheet_meta))
                continue
            if not in_table:
                table_cols = [i for i, _ in filled]
                lo, hi = table_cols[0], table_cols[-1]
            else:
                lo, hi = table_cols[0], max(table_cols[-1], filled[-1][0])
            table_rows.append(vals[lo: hi + 1])
            table_refs.append(SourceRef(file=name, sheet=sheet, row=r))
        close()


def _looks_like_data(first_row: list[str]) -> bool:
    """A table without a header row starts directly with data: long cells or numbers."""
    cells = [c for c in first_row if c]
    return bool(cells) and (max(len(c) for c in cells) > 80 or all(c.replace(".", "").isdigit() for c in cells))


__all__ = ["XlsxReader", "get_column_letter"]
