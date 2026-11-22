"""Requirement Troubleshooter: answers "where is this requirement written?" questions.

Search is deterministic (RequirementIndex); the LLM only writes the explanation from the
passages found. Citations to passages that were not found are discarded. With the mock
provider (or if the LLM fails) a rule-based answer is produced, so it also works offline.
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from ..agents.base import BaseAgent
from ..core.llm import LLMClient, MockLLM
from .index import Hit, RequirementIndex, TestRef


class LLMAnswer(BaseModel):
    found: bool
    answer: str
    used_sources: list[str] = []
    impact: str
    suggestion: str


class Source(BaseModel):
    ref: str            # S1
    label: str          # file, sheet, row / page
    item_id: Optional[str] = None
    section: str = ""
    text: str
    match: str          # id | trace | keyword


class RelatedTest(BaseModel):
    id: str
    scenario: str
    title: str
    why: str


class TroubleshootAnswer(BaseModel):
    question: str
    found: bool
    answer: str
    sources: list[Source]
    related_tests: list[RelatedTest]
    conflicts: list[str]
    gaps: list[str]
    scenarios: list[str]
    impact: str
    suggestion: str
    mode: str           # ai | offline
    tests_available: bool


class Troubleshooter(BaseAgent):
    role = "troubleshooter"
    prompt_file = "troubleshooter.md"
    min_keyword_coverage = 0.6

    def __init__(self, llm: LLMClient, index: RequirementIndex, context: dict | None = None):
        super().__init__(llm, context)
        self.index = index

    # ------------------------------------------------------------ public
    def ask(self, question: str) -> TroubleshootAnswer:
        idx = self.index
        named = idx.tests_named(question)
        # a question about a test case is answered from the requirement behind it
        search_text = question + " " + " ".join(
            " ".join([t.title, t.expected_result, *t.acceptance_criteria, *t.traceability]) for _, t in named)
        hits = idx.search(search_text)
        sources = [Source(ref=f"S{i}", label=h.item.ref.label(), item_id=h.item.item_id, section=h.item.section,
                          text=_readable(h.item), match=h.why)
                   for i, h in enumerate(hits, 1)]
        likely_found = bool(hits) and (hits[0].why in ("id", "trace")
                                       or idx.coverage(question, hits[0]) >= self.min_keyword_coverage
                                       or (bool(named) and idx.coverage(search_text, hits[0]) >= 0.25))
        # when nothing answers the question, related tests/conflicts would only be noise
        tests = idx.related_tests(hits, search_text) if likely_found else []
        conflicts = idx.related_conflicts(hits, question) if likely_found else []
        gaps = idx.related_gaps(tests, question)
        scen = [f"{k}: {idx.scenarios.get(k, k)}" for k in idx.scenarios_of(idx.strong(hits))] if likely_found else []
        base = dict(question=question, sources=sources, scenarios=scen, tests_available=bool(idx.tests),
                    related_tests=[RelatedTest(id=t.test.id, scenario=t.scenario, title=t.test.title, why=t.why)
                                   for t in tests],
                    conflicts=[f"{c.id}: {c.description}" for c in conflicts],
                    gaps=[f"{g.id} ({s}): {g.description}" for s, g in gaps])

        if not isinstance(self.llm, MockLLM) and hits:
            try:
                return self._ask_llm(question, hits, sources, tests, conflicts, gaps, scen, base)
            except Exception:  # noqa: BLE001 - fall back to the rule-based answer rather than fail
                pass
        return self._offline(question, hits, sources, tests, conflicts, gaps, scen, likely_found, base, named)

    # ------------------------------------------------------------ LLM
    def _ask_llm(self, question, hits, sources, tests, conflicts, gaps, scen, base) -> TroubleshootAnswer:
        parts = [f"QUESTION: {question}", "", "SOURCES:"]
        parts += [f"[{s.ref}] ({s.label}; section: {s.section}) {s.item_id + ' — ' if s.item_id else ''}{s.text}"
                  for s in sources]
        parts += ["", "SCENARIOS: " + "; ".join(scen)]
        parts += ["", "RELATED TEST CASES:"] + ([f"- {t.test.id} [{t.scenario}] {t.test.title} ({t.why})"
                                                for t in tests] or ["(none generated yet)"])
        parts += ["", "CONFLICTS:"] + ([f"- {c.id}: {c.description}" for c in conflicts] or ["(none)"])
        parts += ["", "OPEN GAPS:"] + ([f"- {g.id}: {g.description}" for _, g in gaps] or ["(none)"])
        out = self.llm.complete_json(self.system_prompt(), "\n".join(parts), LLMAnswer, role=self.role)
        valid = {s.ref for s in sources}
        used = [u.strip("[] ") for u in out.used_sources if u.strip("[] ") in valid]
        # drop citations to sources that were never provided
        answer = re.sub(r"\[(S\d+)\]", lambda m: m.group(0) if m.group(1) in valid else "", out.answer)
        found = out.found and bool(used)
        ordered = [s for s in sources if s.ref in used] + [s for s in sources if s.ref not in used]
        return TroubleshootAnswer(found=found, answer=answer, impact=out.impact, suggestion=out.suggestion,
                                  mode="ai", **{**base, "sources": ordered})

    # ------------------------------------------------------------ offline
    def _offline(self, question, hits: list[Hit], sources, tests: list[TestRef], conflicts, gaps, scen,
                 found, base, named=()) -> TroubleshootAnswer:
        idx = self.index
        if named and not found:
            scn, tc = named[0]
            answer = (f"{tc.id} ({scn}) checks: {tc.title}. It traces to {', '.join(tc.traceability) or 'no requirement ID'}, "
                      f"but no matching requirement text was found in these documents, so its expected result is not "
                      f"backed by a written requirement.")
        elif not hits:
            answer = "This is not stated in the requirement documents, and nothing closely related was found."
        elif found and named:
            scn, tc = named[0]
            top = sources[0]
            answer = (f"{tc.id} ({scn}) checks: {tc.title}. Expected: {_clip(tc.expected_result, 160)} "
                      f"It traces to {', '.join(tc.traceability) or 'no requirement ID'}; the closest requirement text is "
                      f"{top.item_id + ' — ' if top.item_id else ''}{_clip(top.text, 220)} [{top.ref}], in {top.label}.")
        elif found:
            top = sources[0]
            versions = [s for s in sources if s.item_id and s.item_id == top.item_id]
            answer = (f"{top.item_id + ' — ' if top.item_id else ''}{_clip(top.text, 320)} [{top.ref}]. "
                      f"Written in {top.label}.")
            if len(versions) > 1:
                answer += (f" Note: {top.item_id} appears {len(versions)} times with different wording "
                           f"({', '.join(v.ref for v in versions)}): check the conflicts below.")
        else:
            close = ", ".join(f"{s.item_id or _clip(s.text, 50)} [{s.ref}]" for s in sources[:3])
            answer = f"This is not stated in the requirement documents. Closest related: {close}."
        test_ids = [t.test.id for t in tests]
        scn_txt = ", ".join(scen) or "the affected scenario"
        if not found:
            impact = ("Because the documents don't specify this, no test case can have a reliable expected result for it: "
                      "testers would have to guess, and the behaviour is effectively untested until the BA answers.")
        elif not idx.tests:
            impact = (f"Affects {scn_txt}. Test cases have not been generated for this batch yet, so the dependent "
                      f"tests can't be listed. Run the agents first.")
        elif test_ids:
            impact = (f"Affects {scn_txt}. {len(test_ids)} test case(s) depend on this ({', '.join(test_ids)}): "
                      f"without a clear requirement their expected results may be wrong, so a real defect could "
                      f"pass unnoticed or a correct behaviour could be reported as a bug.")
        else:
            impact = (f"Affects {scn_txt}. No generated test case covers this yet, which is a coverage gap: "
                      f"this behaviour would not be tested at all.")
        if conflicts or gaps:
            impact += " Already raised: " + ", ".join([c.id for c in conflicts] + [g.id for _, g in gaps]) + "."
        if found:
            suggestion = f"Use {sources[0].label} as the source for expected values in the related test cases."
            if conflicts:
                suggestion = f"Ask the BA to resolve {conflicts[0].id} first: the documents disagree on this."
        else:
            suggestion = f"Raise a gap for the BA: \"{question.strip().rstrip('?')}?\" (not specified in the documents)."
        return TroubleshootAnswer(found=found, answer=answer, impact=impact, suggestion=suggestion,
                                  mode="offline", **base)


_NOISE = re.compile(r"^(scenario|scenarios|status|domain|module|priority|attribute)$|trace|brd ref|parent", re.I)


def _readable(item) -> str:
    """Requirement text without its ID repeated and without bookkeeping columns."""
    if item.fields:
        return "; ".join(f"{k}: {v}" for k, v in item.fields.items()
                         if v != item.item_id and not _NOISE.search(k)).replace("\n", " / ")
    text = item.text
    if item.item_id and text.startswith(item.item_id):
        text = text[len(item.item_id):].lstrip(" —–-:")
    return text


def _clip(t: str, n: int) -> str:
    return t if len(t) <= n else t[: n - 1] + "…"
