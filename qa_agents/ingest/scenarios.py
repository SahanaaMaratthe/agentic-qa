"""Scenario discovery, cross-document matching (BRD <-> BRS) and item assignment.

1. Scenario finders (plug-ins) collect *mentions* ("Scenario 1: eDDTS", "Module A — ...")
2. `cluster_mentions` merges mentions within a document by ordinal, then across
   documents by name similarity / shared acronyms / ordinal, into Scenarios
3. The assigner (plug-in) puts every item into scenario(s) or "shared"
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .model import IngestedDocument, Item, Scenario
from .profile import ClientProfile
from .registry import get, register
from .tables import detect_id_column, detect_scenario_column, is_shared_label, norm, scenario_mentions

SHARED = "SHARED"


@dataclass
class Mention:
    doc: str
    ordinal: int
    kind: str
    name: str
    source: str          # column | heading | definition_row | paragraph


# ------------------------------------------------------------------ helpers
def ordinal_of(raw: str) -> int:
    raw = raw.strip()
    return int(raw) if raw.isdigit() else ord(raw.upper()) - 64


def name_after(text: str, m: re.Match, next_start: Optional[int]) -> str:
    seg = text[m.end(): next_start if next_start is not None else len(text)]
    seg = re.sub(r"^\s*(\(\s*primary\s*\))?\s*[:\-—–.)&,]*\s*", "", seg, flags=re.I)
    seg = re.split(r"\s*(?::\s|\|)", seg, maxsplit=1)[0]
    seg = re.sub(r"[\s&,;:(\-—–]+$", "", seg)
    if seg.count("(") > seg.count(")"):
        seg = seg[: seg.rfind("(")].rstrip()
    return norm(seg)[:100]


_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def tokens(text: str, profile: ClientProfile) -> set[str]:
    stop = {s.lower() for s in profile.stop_words}
    out = set()
    for t in _TOKEN.findall(text or ""):
        w = t.lower()
        if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if len(w) >= 3 and w not in stop:
            out.add(w)
    return out


def acronyms(text: str) -> set[str]:
    """eDDTS, UGC, NAD: tokens with 2+ capitals (not at the start only)."""
    return {t.lower() for t in _TOKEN.findall(text or "") if sum(c.isupper() for c in t) >= 2 and len(t) >= 3}


def mentions_in(text: str, profile: ClientProfile) -> list[tuple[int, str, str]]:
    ms = scenario_mentions(text, profile)
    out = []
    for i, m in enumerate(ms):
        nxt = ms[i + 1].start() if i + 1 < len(ms) else None
        out.append((ordinal_of(m.group("ord")), m.group("kind").lower(), name_after(text, m, nxt)))
    return out


# ------------------------------------------------------------------ finders
class ScenarioFinder:
    plugin_name = "base"

    def find(self, doc: IngestedDocument, profile: ClientProfile) -> list[Mention]:
        raise NotImplementedError


@register("scenario_finder", "scenario_column")
class ScenarioColumnFinder(ScenarioFinder):
    def find(self, doc, profile):
        out = []
        for b in doc.blocks:
            if b.kind != "table":
                continue
            ov = profile.sheet_override(b.ref.sheet) if b.ref.sheet else None
            if ov and ov.scenario_column:
                b.meta["scenario_column"] = ov.scenario_column
            col = detect_scenario_column(b, profile, detect_id_column(b, profile))
            b.meta["scenario_column"] = col or ""
            if not col:
                continue
            for r in b.rows:
                for o, k, n in mentions_in(r.cells.get(col, ""), profile):
                    out.append(Mention(doc.name, o, k, n, "column"))
        return out


@register("scenario_finder", "scenario_heading")
class ScenarioHeadingFinder(ScenarioFinder):
    lead = re.compile(r"^\s*(\d{1,2}[.)]\s+|[•\-–▪●]\s*)?")

    def find(self, doc, profile):
        out = []
        for b in doc.blocks:
            if b.kind == "heading":
                for o, k, n in mentions_in(b.text, profile):
                    out.append(Mention(doc.name, o, k, n, "heading"))
            elif b.kind in ("paragraph", "list_item"):
                text = self.lead.sub("", b.text, count=1)
                ms = scenario_mentions(text, profile)
                if ms and ms[0].start() == 0:
                    for o, k, n in mentions_in(text, profile)[:1]:
                        out.append(Mention(doc.name, o, k, n, "paragraph"))
        return out


@register("scenario_finder", "scenario_definition_row")
class ScenarioDefinitionRowFinder(ScenarioFinder):
    """Rows like  | Scenario 1 | Electronic Document Delivery ... |  or  | UC-003 | Reset password |"""

    def find(self, doc, profile):
        out = []
        for b in doc.blocks:
            if b.kind != "table":
                continue
            for r in b.rows:
                vals = list(r.cells.values())
                for i, v in enumerate(vals):
                    ms = scenario_mentions(v, profile)
                    if len(ms) == 1 and ms[0].start() == 0 and ms[0].end() >= len(v.strip()) - 1:
                        nxt = next((x for x in vals[i + 1:] if x), "")
                        name = re.split(r"\s*(?::\s|\|)", nxt, maxsplit=1)[0][:100]
                        out.append(Mention(doc.name, ordinal_of(ms[0].group("ord")), ms[0].group("kind").lower(),
                                           norm(name), "definition_row"))
                        break
        return out


# ------------------------------------------------------------------ clustering
@dataclass
class _Group:
    docs: set
    ordinals: dict                     # doc -> ordinal
    names: list = field(default_factory=list)
    sources: set = field(default_factory=set)


def cluster_mentions(mentions: list[Mention], profile: ClientProfile, doc_order: list[str]):
    """Returns (scenarios, mapping[(doc, ordinal)] -> scenario key)."""
    local: dict[tuple[str, int], _Group] = {}
    for m in mentions:
        g = local.setdefault((m.doc, m.ordinal), _Group(docs={m.doc}, ordinals={m.doc: m.ordinal}))
        if m.name:
            g.names.append(m.name)
        g.sources.add(m.source)

    alias_map = {a.lower(): canon for canon, al in profile.scenario_aliases.items() for a in al}
    for g in local.values():
        for n in list(g.names):
            for a, canon in alias_map.items():
                if a in n.lower():
                    g.names.append(canon)

    def feats(g):
        txt = " ".join(g.names)
        return tokens(txt, profile), acronyms(txt)

    clusters = list(local.values())
    pairs = []
    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            a, b = clusters[i], clusters[j]
            if a.docs & b.docs:
                continue
            (ta, aa), (tb, ab) = feats(a), feats(b)
            same_ord = set(a.ordinals.values()) & set(b.ordinals.values())
            if ta and tb:
                score = len(ta & tb) / len(ta | tb) + (0.5 if aa & ab else 0) + (0.25 if same_ord else 0)
            else:
                score = 0.5 if same_ord else 0.0
            if score >= 0.5:
                pairs.append((score, i, j))
    parent = list(range(len(clusters)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    members = {i: {i} for i in range(len(clusters))}
    for score, i, j in sorted(pairs, reverse=True):
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        docs_i = set().union(*(clusters[k].docs for k in members[ri]))
        docs_j = set().union(*(clusters[k].docs for k in members[rj]))
        if docs_i & docs_j:
            continue
        parent[rj] = ri
        members[ri] |= members.pop(rj)

    order = {d: n for n, d in enumerate(doc_order)}
    groups = []
    for root, idxs in members.items():
        gs = [clusters[k] for k in idxs]
        names = [n for g in gs for n in g.names]
        ords = [o for g in gs for o in g.ordinals.values()]
        docs = sorted({d for g in gs for d in g.docs}, key=lambda d: order.get(d, 99))
        groups.append((min(ords), min(order.get(d, 99) for d in docs), names, gs, docs))
    groups.sort(key=lambda x: (x[0], x[1]))

    scenarios, mapping = [], {}
    all_tokens = []
    for n, (ordinal, _, names, gs, docs) in enumerate(groups, 1):
        key = f"SCN-{n:02d}"
        uniq = list(dict.fromkeys(x for x in names if tokens(x, profile)))
        best = sorted(uniq, key=lambda x: (bool(acronyms(x)), min(len(x), 90)), reverse=True)
        name = best[0] if best else f"Scenario {ordinal}"
        scenarios.append(Scenario(key=key, name=name, aliases=[x for x in uniq if x != name][:8],
                                  ordinal=ordinal, found_in=docs))
        all_tokens.append((tokens(" ".join(names), profile), acronyms(" ".join(names))))
        for g in gs:
            for d, o in g.ordinals.items():
                mapping[(d, o)] = key
    # distinctive keywords only: drop tokens that belong to more than one scenario
    for i, sc in enumerate(scenarios):
        others = set().union(*(t for j, (t, _) in enumerate(all_tokens) if j != i)) if len(all_tokens) > 1 else set()
        toks, acr = all_tokens[i]
        sc.keywords = sorted((toks - others) | (acr - others))
    return scenarios, mapping


# ------------------------------------------------------------------ assignment
class Assigner:
    plugin_name = "base"

    def assign(self, items: list[Item], scenarios: list[Scenario], mapping: dict, profile: ClientProfile) -> None:
        raise NotImplementedError


@register("assigner", "explicit_then_keyword")
class ExplicitThenKeyword(Assigner):
    """explicit label > enclosing heading > sheet override > distinctive keywords > shared."""

    generic_share = 0.4

    def assign(self, items, scenarios, mapping, profile):
        keys_by_name = {s.name.lower(): s.key for s in scenarios}
        weights = self._keyword_weights(items, scenarios, profile)
        for it in items:
            keys = None
            if it.front_matter and not it.scenario_hint:
                it.scenarios, it.assigned_by = [SHARED], "front-matter"
                continue
            if it.scenario_hint:
                keys = self._from_label(it.scenario_hint, it.doc, mapping, profile)
                if keys is not None:
                    it.assigned_by = "explicit" if keys != [SHARED] else "explicit-shared"
            if keys is None and it.has_scenario_column:
                keys, it.assigned_by = [SHARED], "explicit-shared"
            if keys is None and it.heading_hint:
                keys = self._from_label(it.heading_hint, it.doc, mapping, profile)
                if keys:
                    it.assigned_by = "heading"
            if keys is None and it.ref.sheet:
                ov = profile.sheet_override(it.ref.sheet)
                if ov.scenario:
                    k = keys_by_name.get(ov.scenario.lower()) or next(
                        (s.key for s in scenarios if ov.scenario.lower() in (s.name + " " + " ".join(s.aliases)).lower()), None)
                    if k:
                        keys, it.assigned_by = [k], "profile"
            if keys is None and profile.keyword_assignment and weights:
                keys = self._by_keywords(it.content() + " " + it.text, weights)
                if keys:
                    it.assigned_by = "keyword"
                else:
                    keys = self._by_keywords(it.section, weights)
                    if keys:
                        it.assigned_by = "keyword-section"
            if not keys:
                keys, it.assigned_by = [SHARED], it.assigned_by or "shared"
            it.scenarios = keys

    @staticmethod
    def _from_label(label, doc, mapping, profile):
        ms = mentions_in(label, profile)
        if ms:
            keys = [mapping[(doc, o)] for o, _, _ in ms if (doc, o) in mapping]
            return list(dict.fromkeys(keys)) or None
        if is_shared_label(label, profile):
            return [SHARED]
        return None

    def _keyword_weights(self, items, scenarios, profile):
        texts = [(it.content() + " " + it.text).lower() for it in items] or [""]
        weights = {}
        for s in scenarios:
            names = [s.name] + s.aliases
            acr = acronyms(" ".join(names))
            short = set().union(*(tokens(n, profile) for n in names if len(tokens(n, profile)) <= 2))
            for kw in s.keywords:
                rx = re.compile(rf"(?<![A-Za-z0-9]){re.escape(kw)}s?(?![A-Za-z0-9])", re.I)
                share = sum(bool(rx.search(t)) for t in texts) / len(texts)
                if kw in acr:
                    weights[(s.key, kw)] = (rx, 3)          # acronym: eDDTS
                elif kw in short:
                    weights[(s.key, kw)] = (rx, 2)          # short label word: "Grievance"
                elif share <= self.generic_share:
                    weights[(s.key, kw)] = (rx, 1)
        return weights

    @staticmethod
    def _by_keywords(text, weights):
        score = defaultdict(int)
        for (key, _), (rx, w) in weights.items():
            if rx.search(text or ""):
                score[key] += w
        if not score:
            return None
        top = max(score.values())
        if top < 2:
            return None
        return [k for k, v in sorted(score.items()) if v >= max(1, 0.25 * top)]


def assign(items, scenarios, mapping, profile):
    get("assigner", profile.assigner)().assign(items, scenarios, mapping, profile)
