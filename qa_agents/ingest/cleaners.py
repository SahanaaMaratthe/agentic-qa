"""Cleaner plug-ins: each takes an IngestedDocument and returns it cleaned.
They run in the order given by the profile's `cleaners:` list."""
from __future__ import annotations

import re
from collections import defaultdict

from .model import Block, IngestedDocument, TableRow
from .profile import ClientProfile
from .registry import register
from .tables import detect_id_column, join_wrapped, norm


class Cleaner:
    plugin_name = "base"

    def apply(self, doc: IngestedDocument, profile: ClientProfile) -> IngestedDocument:
        raise NotImplementedError


@register("cleaner", "skip_sheets")
class SkipSheets(Cleaner):
    """Drops cover / revision-history / sign-off sheets, hidden sheets and sheets the profile marks skip."""

    def apply(self, doc, profile):
        if doc.format != "xlsx":
            return doc
        skipped, keep = set(), []
        for b in doc.blocks:
            sheet = b.ref.sheet or ""
            reason = None
            if b.meta.get("sheet_override_skip"):
                reason = "profile"
            elif b.meta.get("sheet_hidden") and profile.skip_hidden_sheets:
                reason = "hidden"
            elif any(re.search(p, sheet) for p in profile.skip_sheet_patterns):
                reason = "name"
            if reason:
                skipped.add((sheet, reason))
            else:
                keep.append(b)
        for sheet, reason in sorted(skipped):
            doc.warnings.append(f"{doc.name}: skipped sheet '{sheet}' ({reason}).")
        doc.blocks = keep
        return doc


@register("cleaner", "drop_page_furniture")
class DropPageFurniture(Cleaner):
    """Removes running headers/footers: text repeated on many pages near the top/bottom, and 'Page x of y'."""

    page_no = re.compile(r"\bpage\s*\d+\s*(of\s*\d+)?\b", re.I)

    def apply(self, doc, profile):
        pages = {b.ref.page for b in doc.blocks if b.ref.page}
        if len(pages) < 2:
            return doc
        key = lambda t: re.sub(r"\d+", "#", norm(t).lower())  # noqa: E731
        seen = defaultdict(set)
        for b in doc.blocks:
            if b.kind in ("paragraph", "list_item", "heading"):
                seen[key(b.text)].add(b.ref.page)
        keep, removed = [], 0
        for b in doc.blocks:
            if b.kind in ("paragraph", "list_item", "heading"):
                edge = False
                if "top" in b.meta and b.meta.get("page_h"):
                    h = b.meta["page_h"]
                    edge = b.meta["top"] < 0.08 * h or b.meta.get("bottom", 0) > 0.92 * h
                repeated = len(seen[key(b.text)]) >= max(2, profile.furniture_min_pages * len(pages))
                if (repeated and edge) or (edge and self.page_no.search(b.text) and len(b.text) < 160):
                    removed += 1
                    continue
            keep.append(b)
        doc.blocks = keep
        return doc


@register("cleaner", "merge_split_tables")
class MergeSplitTables(Cleaner):
    """Re-joins a table that continues on the next page (with or without a repeated header row)."""

    def apply(self, doc, profile):
        out: list[Block] = []
        for b in doc.blocks:
            prev = out[-1] if out else None
            if (b.kind == "table" and prev is not None and prev.kind == "table" and b.ref.page and prev.ref.page
                    and b.ref.page == prev.ref.page + 1 and len(b.headers) == len(prev.headers)):
                if [norm(h).lower() for h in b.headers] != [norm(h).lower() for h in prev.headers]:
                    # no repeated header: the "header" of this piece is really a data row
                    raw = b.meta.get("raw_header") or b.headers
                    cells = {h: join_wrapped(v) for h, v in zip(prev.headers, raw) if join_wrapped(v or "")}
                    if cells:
                        prev.rows.append(TableRow(cells=cells, ref=b.ref))
                for r in b.rows:
                    prev.rows.append(TableRow(cells={ph: r.cells[h] for ph, h in zip(prev.headers, b.headers) if h in r.cells},
                                              ref=r.ref))
                prev.meta["merged_pages"] = prev.meta.get("merged_pages", [prev.ref.page]) + [b.ref.page]
                continue
            out.append(b)
        doc.blocks = out
        return doc


@register("cleaner", "group_multirow_records")
class GroupMultirowRecords(Cleaner):
    """One record written over several rows (ID only on the first row, or merged ID cells) becomes one row."""

    def apply(self, doc, profile):
        for b in doc.blocks:
            if b.kind != "table" or not b.rows:
                continue
            id_col = detect_id_column(b, profile)
            b.meta["id_column"] = id_col or ""
            anchor = id_col or (b.headers[0] if b.headers else None)
            if anchor is None:
                continue
            grouped: list[TableRow] = []
            for r in b.rows:
                key = r.cells.get(anchor, "")
                prev = grouped[-1] if grouped else None
                continuation = prev is not None and (not key or (id_col and key == prev.cells.get(anchor)))
                if continuation and (id_col or len(r.cells) < len(b.headers)):
                    for h, v in r.cells.items():
                        if h == anchor:
                            continue
                        old = prev.cells.get(h, "")
                        if v and v not in old:
                            prev.cells[h] = f"{old}\n{v}" if old else v
                    b.meta["grouped_rows"] = b.meta.get("grouped_rows", 0) + 1
                    continue
                grouped.append(r)
            b.rows = grouped
        return doc


@register("cleaner", "drop_empty")
class DropEmpty(Cleaner):
    def apply(self, doc, profile):
        doc.blocks = [b for b in doc.blocks
                      if (b.kind == "table" and b.rows) or (b.kind != "table" and len(norm(b.text)) > 1)]
        return doc
