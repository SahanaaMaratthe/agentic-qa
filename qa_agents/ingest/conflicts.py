"""Conflict-detector plug-ins. Each returns Conflicts; every conflict becomes a gap for the BA.

Rule-based detection catches what is certain (same ID, different text; same fact,
different number). Contradictions that need understanding (e.g. two different
state machines) are left to the Requirement Analyst, whose prompt asks for them.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from itertools import combinations

from .model import Conflict, IngestedDocument, Item
from .profile import ClientProfile
from .registry import register
from .scenarios import SHARED, tokens
from .tables import norm


class ConflictDetector:
    plugin_name = "base"

    def detect(self, items: list[Item], docs: list[IngestedDocument], profile: ClientProfile) -> list[Conflict]:
        raise NotImplementedError


def _body(it: Item) -> str:
    """Comparable content: values only (headers differ between formats), without ID/scenario/status noise."""
    if it.fields:
        vals = [v for k, v in it.fields.items()
                if v != it.item_id and not re.search(r"scenario|status|domain|module", k, re.I)]
        return norm(" ".join(vals)).lower()
    t = it.text
    if it.item_id:
        t = t.replace(it.item_id, " ")
    return norm(t).lower()


NOISE_COL = re.compile(r"^(scenario|scenarios|status|domain|module|priority|category|ref)$|trace|brd ref|parent", re.I)
TITLE_COL = re.compile(r"title|name|feature|objective|goal|rule|requirement|function|stage|area|entity", re.I)


def _excerpt(it: Item, n: int = 110) -> str:
    if it.fields:
        vals = [(k, v) for k, v in it.fields.items() if v != it.item_id and not NOISE_COL.search(k)]
        titled = [v for k, v in vals if TITLE_COL.search(k)]
        txt = (titled or [v for _, v in vals] or [""])[0]
    else:
        txt = it.text.replace(it.item_id, "", 1).lstrip(" —–-:") if it.item_id else it.text
    txt = norm(txt)
    return txt if len(txt) <= n else txt[: n - 1] + "…"


def _scen(*its: Item) -> list[str]:
    return sorted({s for it in its for s in it.scenarios if s != SHARED})


@register("conflict_detector", "same_id_different_content")
class SameIdDifferentContent(ConflictDetector):
    def detect(self, items, docs, profile):
        by_id = defaultdict(list)
        for it in items:
            if it.item_id:
                by_id[it.item_id.upper()].append(it)
        out = []
        for iid, group in sorted(by_id.items()):
            if len(group) < 2:
                continue
            differing = []
            for a, b in combinations(group, 2):
                ratio = difflib.SequenceMatcher(None, _body(a), _body(b)).ratio()
                if ratio < profile.conflict_similarity_threshold:
                    differing.append((a, b, ratio))
            if not differing:
                continue
            versions = list({x.uid: x for a, b, _ in differing for x in (a, b)}.values())
            desc = f"{group[0].item_id} is defined differently in {len(versions)} places: " + "; ".join(
                f"'{_excerpt(v)}' ({v.ref.label()})" for v in versions)
            out.append(Conflict(id="", kind="same_id_different_content", description=desc,
                                question=f"Which definition of {group[0].item_id} is correct and current?",
                                sources=[v.ref.label() for v in versions], scenarios=_scen(*versions)))
        return out


@register("conflict_detector", "document_version_mismatch")
class DocumentVersionMismatch(ConflictDetector):
    """Two files carrying the same document ID but different requirement sets."""

    def detect(self, items, docs, profile):
        out = []
        by_docid = defaultdict(list)
        for d in docs:
            for did in d.doc_ids:
                by_docid[did].append(d.name)
        ids_by_doc, spelled = defaultdict(set), {}
        for it in items:
            if it.item_id:
                ids_by_doc[it.doc].add(it.item_id.upper())
                spelled.setdefault(it.item_id.upper(), it.item_id)
        for did, names in by_docid.items():
            names = list(dict.fromkeys(names))
            if len(names) < 2:
                continue
            for a, b in combinations(names, 2):
                only_a = [spelled[x] for x in sorted(ids_by_doc[a] - ids_by_doc[b])]
                only_b = [spelled[x] for x in sorted(ids_by_doc[b] - ids_by_doc[a])]
                if not (only_a or only_b):
                    continue
                desc = (f"'{a}' and '{b}' both carry document ID {did} but contain different requirements. "
                        f"Only in {a}: {', '.join(only_a[:15]) or 'none'}{' …' if len(only_a) > 15 else ''}. "
                        f"Only in {b}: {', '.join(only_b[:15]) or 'none'}{' …' if len(only_b) > 15 else ''}.")
                out.append(Conflict(id="", kind="document_version_mismatch", description=desc,
                                    question=f"Which file is the authoritative version of {did}? Should the other be ignored?",
                                    sources=[a, b]))
        return out


_NUM_UNIT = re.compile(
    r"(\d+(?:\.\d+)?)\s*(%|ms\b|milliseconds?|secs?\b|seconds?|minutes?|mins?\b|hours?|hrs?\b|days?|working days|"
    r"weeks?|months?|years?|mb\b|gb\b|kb\b|users?|copies|characters?|chars?\b|digits?|attempts?|cycles?|times\b)", re.I)


def _facts(text: str) -> dict[str, set[str]]:
    out = defaultdict(set)
    for num, unit in _NUM_UNIT.findall(text or ""):
        u = unit.lower().rstrip("s") if unit != "%" else "%"
        u = {"sec": "second", "min": "minute", "hr": "hour", "char": "character", "millisecond": "ms"}.get(u, u)
        out[u].add(num.rstrip("0").rstrip(".") if "." in num else num)
    return out


def _title(it: Item) -> str:
    if it.fields:
        shortish = [v for k, v in it.fields.items() if v != it.item_id and len(v) <= 70
                    and not re.search(r"status|priority|scenario|domain|trace|verification|compliance", k, re.I)]
        return " ".join(shortish[:2])
    text = it.text.replace(it.item_id, "", 1).lstrip(" —–-:") if it.item_id else it.text
    return re.split(r"[:—–]", text, maxsplit=1)[0][:90]


@register("conflict_detector", "similar_item_different_numbers")
class SimilarItemDifferentNumbers(ConflictDetector):
    """Items in different documents about the same thing (similar titles) stating different numbers."""

    min_title_similarity = 0.5

    def detect(self, items, docs, profile):
        out, seen = [], set()
        cand = [(it, tokens(_title(it), profile), _facts(it.content() or it.text)) for it in items]
        cand = [c for c in cand if c[1] and c[2]]
        for (a, ta, fa), (b, tb, fb) in combinations(cand, 2):
            if a.doc == b.doc or (a.item_id and b.item_id and a.item_id.upper() == b.item_id.upper()):
                continue
            sim = len(ta & tb) / len(ta | tb)
            if sim < self.min_title_similarity:
                continue
            diffs = [f"{'/'.join(sorted(fa[u]))}{u if u == '%' else ' ' + u} vs {'/'.join(sorted(fb[u]))}"
                     f"{u if u == '%' else ' ' + u}" for u in fa.keys() & fb.keys() if fa[u] != fb[u]]
            if not diffs:
                continue
            key = tuple(sorted((a.uid, b.uid)))
            if key in seen:
                continue
            seen.add(key)
            la, lb = a.item_id or _title(a)[:40], b.item_id or _title(b)[:40]
            out.append(Conflict(id="", kind="similar_item_different_numbers", confidence="medium",
                                description=f"{la} ({a.ref.label()}) and {lb} ({b.ref.label()}) seem to describe the "
                                            f"same requirement but state different values: {'; '.join(diffs)}.",
                                question=f"Which value is correct for '{_title(a)[:60]}'?",
                                sources=[a.ref.label(), b.ref.label()], scenarios=_scen(a, b)))
        return out


_FIELD_LEN = re.compile(r"\b([A-Za-z][A-Za-z_ ]{1,30}?)\s*\(\s*(VARCHAR|CHAR|NVARCHAR|INT|NUMBER|DECIMAL)\s*\(?\s*(\d+)", re.I)


@register("conflict_detector", "field_length_mismatch")
class FieldLengthMismatch(ConflictDetector):
    """Same data field declared with different types/lengths in different documents (e.g. USN VARCHAR 10 vs 12)."""

    def detect(self, items, docs, profile):
        decl = defaultdict(list)
        for it in items:
            for fname, typ, ln in _FIELD_LEN.findall(it.content() or it.text):
                f = re.sub(r"^(pk|fk|primary key|foreign key)\s*:?\s*", "", fname.strip().lower())
                decl[f.split()[-1]].append((f"{typ.upper()} {ln}", it))
        out = []
        for f, uses in sorted(decl.items()):
            kinds = {k for k, _ in uses}
            docs_involved = {it.doc for _, it in uses}
            if len(kinds) > 1 and len(docs_involved) > 1:
                srcs = list(dict.fromkeys(f"{k} ({it.ref.label()})" for k, it in uses))
                out.append(Conflict(id="", kind="field_length_mismatch",
                                    description=f"Field '{f}' is declared differently: {'; '.join(srcs)}.",
                                    question=f"What is the correct type and length of '{f}'?",
                                    sources=[it.ref.label() for _, it in uses], scenarios=_scen(*[it for _, it in uses])))
        return out
