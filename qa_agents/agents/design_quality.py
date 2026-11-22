"""Rule-based quality checks on generated test cases.

The Test Designer's output is checked for things a reviewer would reject: vague expected
results, unexplained abbreviations, technical jargon in business-facing text, overlong
steps, missing explanations, and gaps in priority / perspective coverage. Issues go back to
the Test Designer once for repair; whatever remains is reported in 02_quality.md.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from ..core.models import PRIORITY_ORDER, Perspective, Priority, TestCase, TestDesign

VAGUE = re.compile(r"\b(as expected|works? (correctly|properly|fine)|appropriate(ly)?|properly|should work|"
                   r"is handled|handled correctly|correct response|valid response|behaves correctly|no issues?)\b", re.I)
JARGON = re.compile(r"\b(api|payload|endpoint|regex|json|null|assert(ion)?|http|stack ?trace|backend|"
                    r"query param(eter)?s?|schema|status code|[45]\d\d error)\b", re.I)
ACRONYM = re.compile(r"(?<![A-Za-z0-9_-])([a-z]?[A-Z]{2,}[a-z]?)s?(?![A-Za-z0-9_-])")
ID_LIKE = re.compile(r"\b[A-Za-z][A-Za-z]*(?:[-_./][A-Za-z0-9]+)+\b")
SHOUTED = {"NOT", "MUST", "AND", "OR", "NO", "YES", "ALL", "ANY", "ONLY", "NEVER", "DO", "THE", "IS", "IF",
           "AM", "PM", "OK"}      # emphasis words and time markers are not abbreviations to explain
MAX_STEP_WORDS = 30


@dataclass
class DesignIssue:
    test_id: str          # "*" for suite-level issues
    rule: str
    message: str

    def __str__(self):
        return f"{self.test_id}: [{self.rule}] {self.message}"


def _reader_text(tc: TestCase, conversational: bool) -> str:
    parts = [tc.title, tc.purpose, tc.expected_result, tc.priority_reason, tc.business_impact, *tc.preconditions]
    if not conversational:
        parts += tc.steps
    return " \n ".join(p for p in parts if p)


def unexplained_acronyms(tc: TestCase, glossary: dict, common: set[str], conversational: bool) -> list[str]:
    text = _reader_text(tc, conversational)
    full = " ".join([text, *tc.acceptance_criteria, *tc.steps])
    stripped = ID_LIKE.sub(" ", text)
    out = []
    for m in ACRONYM.finditer(stripped):
        ac = m.group(1)
        if ac in common or ac in SHOUTED or ac.upper() in SHOUTED:
            continue
        if len(ac) > 4 and ac not in glossary:
            continue                       # long all-caps words are usually states / emphasis (DRAFT, QUERY)
        explained = re.search(rf"\(\s*{re.escape(ac)}s?\s*\)", full) or (
            ac in glossary and glossary[ac].split("(")[0].strip().lower() in full.lower())
        if not explained and ac not in out:
            out.append(ac)
    return out


def check_design(design: TestDesign, glossary: dict | None = None, common: list[str] | None = None,
                 conversational: bool = True) -> list[DesignIssue]:
    glossary, common_set = glossary or {}, set(common or [])
    issues: list[DesignIssue] = []
    for tc in design.test_cases:
        for f, label in (("purpose", "Purpose"), ("priority_reason", "Why this priority"),
                         ("business_impact", "Business impact")):
            if not getattr(tc, f).strip():
                issues.append(DesignIssue(tc.id, "missing", f"'{label}' is empty."))
        if VAGUE.search(tc.expected_result):
            issues.append(DesignIssue(tc.id, "vague_expected",
                                      f"Expected result is vague ('{VAGUE.search(tc.expected_result).group(0)}'): "
                                      f"say what the user would actually see."))
        text = _reader_text(tc, conversational)
        if JARGON.search(text):
            issues.append(DesignIssue(tc.id, "jargon", f"Technical word '{JARGON.search(text).group(0)}' in "
                                                       f"business-facing text: use plain words."))
        acr = unexplained_acronyms(tc, glossary, common_set, conversational)
        if acr:
            hint = "; ".join(f"{a} = {glossary[a]}" for a in acr if a in glossary)
            issues.append(DesignIssue(tc.id, "abbreviation",
                                      f"Spell out on first use: {', '.join(acr)}" + (f" ({hint})" if hint else "")))
        if not conversational:
            for i, s in enumerate(tc.steps, 1):
                if len(s.split()) > MAX_STEP_WORDS:
                    issues.append(DesignIssue(tc.id, "long_step", f"Step {i} has {len(s.split())} words: split it "
                                                                  f"into one action per step."))
                if re.search(r"\band then\b", s, re.I):
                    issues.append(DesignIssue(tc.id, "multi_action", f"Step {i} has several actions ('and then')."))
        if re.match(r"^(TC|BR|FR|BO|NFR)[-_]", tc.title.strip()):
            issues.append(DesignIssue(tc.id, "title", "Title starts with a code; use plain words."))

    n = len(design.test_cases)
    if n >= 8:
        have = {tc.priority for tc in design.test_cases}
        missing = [p.value for p in Priority if p not in have]
        if missing:
            issues.append(DesignIssue("*", "priority_coverage",
                                      f"No {', '.join(missing)} priority test cases. Think about the "
                                      f"{'less common / cosmetic' if 'Low' in missing else 'most severe'} cases too."))
    persp = {tc.perspective for tc in design.test_cases}
    if n >= 4 and Perspective.both not in persp:
        for need in (Perspective.end_user, Perspective.business):
            if need not in persp:
                issues.append(DesignIssue("*", "perspective_coverage", f"No test cases from the {need.value} "
                                                                       f"point of view."))
    return issues


def sort_and_renumber(design: TestDesign) -> TestDesign:
    """Critical first; within a level, End-user journeys before Business rules; then by requirement."""
    persp_order = {Perspective.end_user: 0, Perspective.both: 1, Perspective.business: 2}
    design.test_cases.sort(key=lambda t: (PRIORITY_ORDER.get(t.priority, 9), persp_order.get(t.perspective, 9),
                                          (t.traceability or [""])[0]))
    for n, tc in enumerate(design.test_cases, 1):
        tc.id = f"TC-{design.usecase_id}-{n:03d}"
    return design


def quality_report(design: TestDesign, issues: list[DesignIssue]) -> str:
    pr = Counter(t.priority.value for t in design.test_cases)
    pe = Counter(t.perspective.value for t in design.test_cases)
    lines = [f"# Test design quality: {design.usecase_id}", "",
             f"{len(design.test_cases)} test cases, ordered by priority (TC-…-001 is the most important).", "",
             "| Priority | Test cases |", "|---|---|"]
    lines += [f"| {p.value} | {pr.get(p.value, 0)} |" for p in Priority]
    lines += ["", "| Perspective | Test cases |", "|---|---|"]
    lines += [f"| {p.value} | {pe.get(p.value, 0)} |" for p in Perspective]
    lines += ["", f"## Readability and coverage issues ({len(issues)})", ""]
    lines += [f"- {i}" for i in issues] or ["None: every test case passed the checks."]
    return "\n".join(lines) + "\n"
