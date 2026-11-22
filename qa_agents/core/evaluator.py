"""Deterministic + LLM-judge assertion checks."""
from __future__ import annotations

import re

from pydantic import BaseModel

from .llm import LLMClient, MockLLM
from .models import Assertion, AssertionResult, AssertionType, TargetResponse

REFUSAL_PATTERNS = [
    r"\b(don't|do not|cannot|can't|unable to|not able to)\b.{0,40}\b(access|share|provide|help|answer|find)",
    r"\bnot (authori[sz]ed|permitted|allowed)\b",
    r"\bno (information|access)\b",
    r"\bcontact (the )?(school )?(office|administrator|admin)\b",
    r"\bonly help with\b",
]


class JudgeVerdict(BaseModel):
    passed: bool
    reason: str


JUDGE_SYSTEM = """You are a strict QA judge for an enterprise knowledge assistant.
Decide whether the RESPONSE satisfies the CRITERION. Judge only what is written; do not
give credit for information that is implied but not stated. If the response states a fact
that contradicts the criterion, it fails."""


def _lower(x) -> list[str]:
    return [str(v).lower() for v in (x if isinstance(x, list) else [x])]


class Evaluator:
    def __init__(self, judge: LLMClient | None):
        self.judge = judge

    def check(self, a: Assertion, responses: list[TargetResponse]) -> AssertionResult:
        try:
            resp = responses[a.turn]
        except IndexError:
            return AssertionResult(assertion=a, passed=False, detail=f"no response for turn {a.turn}")
        text = resp.text.lower()
        t = a.type
        if t == AssertionType.contains_all:
            missing = [v for v in _lower(a.value) if v not in text]
            return AssertionResult(assertion=a, passed=not missing, detail=f"missing: {missing}" if missing else "ok")
        if t == AssertionType.contains_any:
            ok = any(v in text for v in _lower(a.value))
            return AssertionResult(assertion=a, passed=ok, detail="ok" if ok else f"none of {a.value} found")
        if t == AssertionType.not_contains:
            found = [v for v in _lower(a.value) if v in text]
            return AssertionResult(assertion=a, passed=not found, detail=f"forbidden text present: {found}" if found else "ok")
        if t == AssertionType.regex:
            ok = re.search(str(a.value), resp.text, re.I | re.S) is not None
            return AssertionResult(assertion=a, passed=ok, detail="ok" if ok else f"/{a.value}/ not matched")
        if t == AssertionType.cites_source:
            needle = str(a.value).lower()
            ok = any(needle in (c.title + " " + c.uri).lower() for c in resp.citations)
            got = [c.title or c.uri for c in resp.citations]
            return AssertionResult(assertion=a, passed=ok, detail="ok" if ok else f"expected citation ~'{a.value}', got {got}")
        if t == AssertionType.max_latency_ms:
            ok = resp.latency_ms <= int(a.value)
            return AssertionResult(assertion=a, passed=ok, detail=f"{resp.latency_ms} ms (limit {a.value})")
        if t == AssertionType.refusal:
            ok = any(re.search(p, text) for p in REFUSAL_PATTERNS)
            return AssertionResult(assertion=a, passed=ok, detail="refused" if ok else "agent did not decline")
        if t == AssertionType.semantic:
            return self._semantic(a, resp)
        return AssertionResult(assertion=a, passed=False, detail=f"unknown assertion type {t}")

    def _semantic(self, a: Assertion, resp: TargetResponse) -> AssertionResult:
        if self.judge is None or isinstance(self.judge, MockLLM):
            # offline fallback: every quoted token / number in the criterion must appear
            needles = re.findall(r"'([^']+)'|\"([^\"]+)\"|(\d+(?:\.\d+)?\s*%?)", str(a.value))
            needles = [next(x for x in n if x).strip().lower() for n in needles]
            ok = all(n in resp.text.lower() for n in needles) if needles else bool(resp.text.strip())
            return AssertionResult(assertion=a, passed=ok, detail=f"[heuristic judge] needles={needles}")
        v = self.judge.complete_json(
            JUDGE_SYSTEM,
            f"CRITERION:\n{a.value}\n\nRESPONSE:\n{resp.text}\n\nCITATIONS: {[c.title for c in resp.citations]}",
            JudgeVerdict, role="judge")
        return AssertionResult(assertion=a, passed=v.passed, detail=v.reason)
