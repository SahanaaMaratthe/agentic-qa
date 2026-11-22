from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

from ..core.evaluator import Evaluator
from ..core.models import (Assertion, AssertionType, ExecutableSuite, ExecutableTest, TestCase,
                           TestCategory, TestDesign, TestResult)
from ..core.target import TargetAgent
from .base import BaseAgent


class AutomationEngineer(BaseAgent):
    """Automation Engineer: test cases -> executable suite, then runs it against the target agent."""

    role = "automation_engineer"
    prompt_file = "automation_engineer.md"
    batch_size = 8

    # ------------------------------------------------------------ convert
    def convert(self, design: TestDesign, target_agent: str) -> ExecutableSuite:
        sys = self.system_prompt(target_agent=target_agent)
        by_id = {tc.id: tc for tc in design.test_cases}
        tests: dict[str, ExecutableTest] = {}
        cases = design.test_cases
        for i in range(0, len(cases), self.batch_size):
            batch = cases[i : i + self.batch_size]
            out = self.llm.complete_json(sys, self.dump(batch), ExecutableSuite, role=self.role)
            for t in out.tests:
                if t.test_id in {b.id for b in batch}:
                    tests[t.test_id] = t
        suite = []
        for tc_id, tc in by_id.items():
            t = tests.get(tc_id)
            if t is None:  # LLM skipped it: fall back to a semantic check per criterion
                t = ExecutableTest(test_id=tc.id, persona=tc.persona, target_agent=target_agent, turns=tc.steps,
                                   assertions=[Assertion(type=AssertionType.semantic, value=c) for c in tc.acceptance_criteria])
            suite.append(self._harden(t, tc, target_agent))
        return ExecutableSuite(usecase_id=design.usecase_id, tests=suite)

    @staticmethod
    def _harden(t: ExecutableTest, tc: TestCase, target_agent: str) -> ExecutableTest:
        """Deterministic guardrails so automation never drifts from the manual test case."""
        t.persona, t.turns, t.target_agent = tc.persona, list(tc.steps), target_agent
        types = {a.type for a in t.assertions}
        expects_denial = re.search(r"\b(declin|refus|must not|cannot share|can't share|not (be )?shown|no access|does not reveal)",
                                   (tc.expected_result + " " + " ".join(tc.acceptance_criteria)).lower())
        if tc.category == TestCategory.access_control and expects_denial and AssertionType.refusal not in types:
            t.assertions.append(Assertion(type=AssertionType.refusal, value=None, description="auto: access-control must decline"))
        if not t.assertions:
            t.assertions = [Assertion(type=AssertionType.semantic, value=c) for c in tc.acceptance_criteria]
        return t

    # ------------------------------------------------------------ execute
    def execute(self, suite: ExecutableSuite, target: TargetAgent, judge, concurrency: int = 4,
                repeats: int = 1) -> list[TestResult]:
        ev = Evaluator(judge)

        def run_one(t: ExecutableTest) -> TestResult:
            attempts = []
            for _ in range(max(1, repeats)):
                t0 = time.time()
                try:
                    responses = target.converse(t.persona, t.target_agent, t.turns)
                    ars = [ev.check(a, responses) for a in t.assertions]
                    ok = all(r.passed for r in ars if r.assertion.critical)
                    attempts.append(TestResult(test_id=t.test_id, persona=t.persona, turns=t.turns,
                                               status="passed" if ok else "failed", responses=responses,
                                               assertion_results=ars, duration_ms=int((time.time() - t0) * 1000)))
                except Exception as e:  # noqa: BLE001
                    attempts.append(TestResult(test_id=t.test_id, persona=t.persona, turns=t.turns, status="error",
                                               error=f"{type(e).__name__}: {e}", duration_ms=int((time.time() - t0) * 1000)))
            statuses = {a.status for a in attempts}
            final = next((a for a in attempts if a.status != "passed"), attempts[0])
            if len(statuses) > 1 and "passed" in statuses:
                final.status = "flaky"  # LLM non-determinism: passed sometimes, failed sometimes
            return final

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            return list(pool.map(run_one, suite.tests))

    # ------------------------------------------------------------ reports
    @staticmethod
    def junit_xml(results: list[TestResult], suite_name: str) -> str:
        fails = sum(r.status in ("failed", "flaky") for r in results)
        errs = sum(r.status == "error" for r in results)
        out = [f'<?xml version="1.0" encoding="UTF-8"?>',
               f'<testsuite name="{escape(suite_name)}" tests="{len(results)}" failures="{fails}" errors="{errs}">']
        for r in results:
            out.append(f'  <testcase classname="{escape(suite_name)}.{escape(r.persona)}" name="{escape(r.test_id)}" time="{r.duration_ms/1000:.2f}">')
            if r.status in ("failed", "flaky"):
                msg = "; ".join(f"{a.assertion.type.value}: {a.detail}" for a in r.assertion_results if not a.passed)
                out.append(f'    <failure message="{escape(msg[:500], {chr(34): "&quot;"})}">{escape(r.responses[-1].text if r.responses else "")}</failure>')
            elif r.status == "error":
                out.append(f'    <error message="{escape(r.error[:500], {chr(34): "&quot;"})}"/>')
            out.append("  </testcase>")
        out.append("</testsuite>")
        return "\n".join(out)

    @staticmethod
    def summary_md(results: list[TestResult]) -> str:
        counts: dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        lines = ["# Execution summary", "", " | ".join(f"**{k}**: {v}" for k, v in sorted(counts.items())), "",
                 "| Test | Persona | Status | Failed checks |", "|---|---|---|---|"]
        for r in results:
            bad = "<br>".join(f"{a.assertion.type.value}: {a.detail}" for a in r.assertion_results if not a.passed) or r.error or ""
            lines.append(f"| {r.test_id} | {r.persona} | {r.status} | {bad.replace('|', '/')} |")
        return "\n".join(lines) + "\n"
