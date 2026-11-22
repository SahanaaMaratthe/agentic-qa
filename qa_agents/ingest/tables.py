"""Helpers shared by readers and cleaners for working with tables."""
from __future__ import annotations

import re
from typing import Optional

from .model import Block, TableRow
from .profile import ClientProfile


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def join_wrapped(s: str) -> str:
    """Join text wrapped inside a cell: 'Vice-\\nChancellor' -> 'Vice-Chancellor'."""
    s = str(s or "")
    s = re.sub(r"(\w)-\n(\w)", r"\1-\2", s)
    return norm(s.replace("\n", " "))


def unique_headers(raw: list[str]) -> list[str]:
    out, seen = [], {}
    for i, h in enumerate(raw):
        h = norm(h) or f"Column {chr(65 + i) if i < 26 else i + 1}"
        if h in seen:
            seen[h] += 1
            h = f"{h} ({seen[h]})"
        else:
            seen[h] = 1
        out.append(h)
    return out


def header_matches(header: str, names: list[str]) -> bool:
    h = norm(header).lower().rstrip(":")
    return any(h == n.lower() for n in names)


def detect_id_column(block: Block, profile: ClientProfile) -> Optional[str]:
    """The column whose values look like requirement IDs (by value first, header name second)."""
    if block.meta.get("id_column") is not None:
        return block.meta["id_column"] or None
    best, best_score = None, 0.0
    for h in block.headers:
        vals = [r.cells.get(h, "") for r in block.rows]
        vals = [v for v in vals if v]
        if not vals:
            continue
        frac = sum(profile.is_id(v) for v in vals) / len(vals)
        uniq = len(set(vals)) / len(vals)
        score = frac * (0.5 + 0.5 * uniq) + (0.3 if header_matches(h, profile.id_column_names) else 0)
        if score > best_score:
            best, best_score = h, score
    if best_score >= 0.6:
        return best
    return None


def scenario_mentions(text: str, profile: ClientProfile) -> list[re.Match]:
    out = []
    for rx in profile.scenario_regexes():
        out.extend(rx.finditer(text or ""))
    out.sort(key=lambda m: m.start())
    # drop overlapping matches
    res, last_end = [], -1
    for m in out:
        if m.start() >= last_end:
            res.append(m)
            last_end = m.end()
    return res


def is_shared_label(text: str, profile: ClientProfile) -> bool:
    t = norm(text).lower()
    return any(re.search(p, t, re.I) for p in profile.shared_labels)


def detect_scenario_column(block: Block, profile: ClientProfile, id_col: Optional[str]) -> Optional[str]:
    """A column whose values mostly name scenarios ('Scenario 1: eDDTS', 'Module A', 'Shared')."""
    if block.meta.get("scenario_column") is not None:
        return block.meta["scenario_column"] or None
    best, best_score = None, 0.0
    for h in block.headers:
        vals = [r.cells.get(h, "") for r in block.rows if r.cells.get(h)]
        if not vals:
            continue
        hits = sum(bool(scenario_mentions(v, profile)) or is_shared_label(v, profile) for v in vals)
        frac = hits / len(vals)
        score = frac + (0.2 if header_matches(h, profile.scenario_column_names) else 0)
        if h == id_col and profile.segment_mode != "per_row":
            score -= 0.5      # an ID column is only a scenario column in per-row mode
        if score > best_score:
            best, best_score = h, score
    return best if best_score >= 0.5 else None


def table_from_rows(raw_rows: list[list[str]], refs: list, first_is_header: bool = True) -> tuple[list[str], list[TableRow]]:
    if not raw_rows:
        return [], []
    width = max(len(r) for r in raw_rows)
    raw_rows = [list(r) + [""] * (width - len(r)) for r in raw_rows]
    if first_is_header:
        headers = unique_headers(raw_rows[0])
        body, body_refs = raw_rows[1:], refs[1:]
    else:
        headers = unique_headers([""] * width)
        body, body_refs = raw_rows, refs
    rows = []
    for r, ref in zip(body, body_refs):
        cells = {h: join_wrapped(v) for h, v in zip(headers, r) if join_wrapped(v)}
        if cells:
            rows.append(TableRow(cells=cells, ref=ref))
    return headers, rows
