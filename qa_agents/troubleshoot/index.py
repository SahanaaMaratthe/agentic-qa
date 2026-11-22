"""Searchable index over one batch: requirement items, test cases, gaps and conflicts.

Finding the right passages is deterministic (ID lookup + keyword ranking), so the
Troubleshooter can only cite text that really exists in the documents.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..core.models import Gap, TestCase, TestDesign
from ..ingest.model import Conflict, Item
from ..ingest.profile import ClientProfile, load_profile

STOP = set("""a an the is are was were be been of to in on for and or not no with by at as it this that these those
what where which who whom whose when why how does do did can could should would will shall may might must
mentioned mention written write say says said find show tell me please about any there their its from into
requirement requirements document documents rule rules qa i we you many much number value
limit allowed maximum minimum max min there's need needs get got""".split())

TEST_ID = re.compile(r"\bTC-[A-Za-z0-9-]+\b", re.I)
CONFLICT_ID = re.compile(r"\bCF-\d{2,}\b", re.I)
GAP_ID = re.compile(r"\bG-\d{2,}\b", re.I)
SCN_ID = re.compile(r"\bSCN-\d{2,}\b", re.I)


_SUFFIXES = ("ations", "ation", "itions", "ition", "ments", "ment", "ness", "ables", "able", "ibles", "ible",
             "ings", "ing", "ies", "ied", "ers", "er", "ed", "es", "ly", "y", "s")


def stem(t: str) -> str:
    """Crude stemmer: expiry / expires / expired / expiration -> expir."""
    if len(t) <= 4 or t[0].isdigit():
        return t
    for suf in _SUFFIXES:
        if t.endswith(suf) and len(t) - len(suf) >= 4:
            return t[: -len(suf)]
    return t


def words(text: str) -> list[str]:
    out = []
    for t in re.findall(r"[A-Za-z][A-Za-z0-9]+|\d+(?:\.\d+)?%?", (text or "").lower()):
        if t not in STOP and len(t) > 1:
            out.append(stem(t))
    return out


@dataclass
class Hit:
    item: Item
    score: float
    why: str                      # "id" | "trace" | "keyword"


@dataclass
class TestRef:
    test: TestCase
    scenario: str
    why: str


@dataclass
class RequirementIndex:
    batch_dir: Path
    items: list[Item]
    conflicts: list[Conflict]
    tests: list[tuple[str, TestCase]] = field(default_factory=list)      # (scenario, test)
    gaps: list[tuple[str, Gap]] = field(default_factory=list)
    scenarios: dict[str, str] = field(default_factory=dict)              # key -> name
    profile: ClientProfile | None = None

    # ------------------------------------------------------------ build
    @classmethod
    def load(cls, batch_dir: Path, profile: ClientProfile | str | None = None) -> "RequirementIndex":
        batch_dir = Path(batch_dir)
        ing = batch_dir / "00_ingest"
        if not (ing / "items.json").exists():
            raise FileNotFoundError(f"No read documents in {batch_dir}. Read documents (preview) first.")
        items = [Item.model_validate(x) for x in json.loads((ing / "items.json").read_text(encoding="utf-8"))]
        rep = json.loads((ing / "report.json").read_text(encoding="utf-8"))
        conflicts = [Conflict.model_validate(c) for c in rep.get("conflicts", [])]
        idx = cls(batch_dir=batch_dir, items=items, conflicts=conflicts,
                  scenarios={s["key"]: s["name"] for s in rep.get("scenarios", [])},
                  profile=profile if isinstance(profile, ClientProfile) else load_profile(profile))
        idx.refresh_tests()
        idx._build()
        return idx

    def refresh_tests(self) -> None:
        """(Re)load test cases and gaps; call again after the agents have run."""
        self.tests, self.gaps = [], []
        for f in sorted(self.batch_dir.glob("SCN-*/02_testcases.json")):
            d = TestDesign.model_validate(json.loads(f.read_text(encoding="utf-8")))
            scn = f.parent.name
            self.tests += [(scn, t) for t in d.test_cases]
            self.gaps += [(scn, g) for g in d.gaps]

    def _build(self) -> None:
        self._docs = [words(self._item_text(it)) for it in self.items]
        self._df = Counter(t for d in self._docs for t in set(d))
        self._avg = sum(len(d) for d in self._docs) / max(1, len(self._docs))

    @staticmethod
    def _item_text(it: Item) -> str:
        return f"{it.item_id or ''} {it.section} {it.content() or it.text}"

    # ------------------------------------------------------------ search
    def ids_in(self, question: str) -> list[str]:
        found = []
        for rx in self.profile.id_regexes():
            found += [m.group(0) for m in rx.finditer(question)]
        known = {it.item_id.upper() for it in self.items if it.item_id}
        return list(dict.fromkeys(i for i in found if i.upper() in known))

    def search(self, question: str, k: int = 8) -> list[Hit]:
        hits: dict[str, Hit] = {}
        for iid in self.ids_in(question):
            for it in self.items:
                if it.item_id and it.item_id.upper() == iid.upper():
                    hits[it.uid] = Hit(it, 100.0, "id")
                elif iid.upper() in (t.upper() for t in it.traces):
                    hits.setdefault(it.uid, Hit(it, 50.0, "trace"))
        q = words(question)
        if q:
            n = len(self._docs)
            for it, doc in zip(self.items, self._docs):
                if not doc:
                    continue
                tf = Counter(doc)
                s = 0.0
                for t in set(q):
                    if t in tf:
                        idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                        s += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(doc) / self._avg))
                if s > 0 and it.uid not in hits:
                    hits[it.uid] = Hit(it, s * (1.3 if it.item_id else 1.0), "keyword")
        ranked = sorted(hits.values(), key=lambda h: -h.score)
        return ranked[:k]

    def idf(self, term: str) -> float:
        n = max(1, len(self._docs))
        df = self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def coverage(self, question: str, hit: Hit) -> float:
        """Share of the question's meaning found in a passage, rare words weighing more (0..1).
        A word that appears nowhere in the documents ("dress") weighs the most."""
        q = set(words(question))
        if not q:
            return 0.0
        found = q & set(words(self._item_text(hit.item)))
        return sum(self.idf(t) for t in found) / sum(self.idf(t) for t in q)

    def strong(self, hits: list[Hit]) -> list[Hit]:
        """The hits that really answer the question: ID/trace matches, or keyword hits close to the best."""
        if not hits:
            return []
        exact = [h for h in hits if h.why in ("id", "trace")]
        if exact:
            return exact[:4]
        top = hits[0].score
        return [h for h in hits[:3] if h.score >= 0.6 * top]

    # ------------------------------------------------------------ related things
    def related_tests(self, hits: list[Hit], question: str, k: int = 6) -> list[TestRef]:
        ids = {h.item.item_id.upper() for h in hits if h.item.item_id}
        explicit_tests = {t.upper() for t in TEST_ID.findall(question)}
        out: dict[str, TestRef] = {}
        for scn, t in self.tests:
            trace = " ".join(t.traceability).upper()
            if t.id.upper() in explicit_tests:
                out[t.id] = TestRef(t, scn, "asked about")
            elif ids and any(i in trace for i in ids):
                out.setdefault(t.id, TestRef(t, scn, "traces to " + ", ".join(sorted(i for i in ids if i in trace))))
        if len(out) < k and hits:
            # topic match: the test must share a RARE question word and >= 2 rare words with the requirement
            q_rare = {t for t in words(question) if self.idf(t) >= 1.5}
            req_rare = {t for h in self.strong(hits) for t in words(self._item_text(h.item)) if self.idf(t) >= 1.5}
            scored = []
            for scn, t in self.tests:
                if t.id in out:
                    continue
                tw = set(words(" ".join([t.title, t.expected_result, *t.acceptance_criteria, *t.steps])))
                if tw & q_rare and len(tw & (req_rare | q_rare)) >= 2:
                    scored.append((sum(self.idf(x) for x in tw & (req_rare | q_rare)), scn, t))
            for _, scn, t in sorted(scored, key=lambda x: -x[0])[: k - len(out)]:
                out[t.id] = TestRef(t, scn, "same topic")
        return list(out.values())[:k]

    def related_conflicts(self, hits: list[Hit], question: str) -> list[Conflict]:
        strong = self.strong(hits)
        refs = {h.item.ref.label() for h in strong}
        ids = {h.item.item_id for h in strong if h.item.item_id}
        asked = {c.upper() for c in CONFLICT_ID.findall(question)}
        picked = [c for c in self.conflicts if c.id.upper() in asked or set(c.sources) & refs
                  or any(i and i in c.description for i in ids)]
        q = {t for t in words(question) if self.idf(t) >= 1.0}

        def rel(c):
            d = set(words(c.description + " " + c.question))
            return (c.id.upper() in asked, c.kind != "document_version_mismatch", len(q & d), -len(c.description))
        return sorted(picked, key=rel, reverse=True)

    def related_gaps(self, tests: list[TestRef], question: str) -> list[tuple[str, Gap]]:
        dep = {t.test.based_on_assumption for t in tests if t.test.based_on_assumption}
        asked = {g.upper() for g in GAP_ID.findall(question) + CONFLICT_ID.findall(question)}
        return [(s, g) for s, g in self.gaps if g.id in dep or g.id.upper() in asked]

    def tests_named(self, question: str) -> list[tuple[str, TestCase]]:
        asked = {t.upper() for t in TEST_ID.findall(question)}
        return [(s, t) for s, t in self.tests if t.id.upper() in asked]

    def scenarios_of(self, hits: list[Hit]) -> list[str]:
        keys = []
        for h in hits:
            for s in h.item.scenarios:
                if s == "SHARED":
                    keys += list(self.scenarios)
                else:
                    keys.append(s)
        return list(dict.fromkeys(keys))
