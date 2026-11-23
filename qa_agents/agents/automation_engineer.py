from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

from pathlib import Path

import yaml

from ..core.evaluator import Evaluator
from ..core.llm import MockLLM
from ..core.models import (Assertion, AssertionType, ExecutableSuite, ExecutableTest, TargetResponse, TestCase,
                           TestCategory, TestDesign, TestResult, WebActionType)
from ..core.target import TargetAgent
from .base import BaseAgent
from .web_steps import expectations_from, parse_steps

PUBLIC_PERSONAS = re.compile(r"\b(public|visitor|guest|anonymous|anyone|not signed in|logged out)\b", re.I)
QUALITY_CHECKS = {"grounded": AssertionType.grounded, "not_toxic": AssertionType.not_toxic,
                  "unbiased": AssertionType.unbiased, "no_pii": AssertionType.no_pii,
                  "resists_injection": AssertionType.resists_injection}


class AutomationEngineer(BaseAgent):
    """Automation Engineer: test cases -> executable suite, then runs it against the target agent."""

    role = "automation_engineer"
    prompt_file = "automation_engineer.md"
    batch_size = 8

    # ------------------------------------------------------------ convert
    def convert(self, design: TestDesign, target_agent: str, kind: str = "conversational",
                page_map: dict | None = None, quality: dict | None = None) -> ExecutableSuite:
        """kind: conversational (chatbot, Gemini Enterprise, Gen AI) | web (browser).
        quality: Gen AI checks added to every AI test, e.g. {"checks": ["no_pii", "not_toxic"], "critical": False}."""
        if kind == "web":
            return self.convert_web(design, target_agent, page_map or {})
        suite = self._convert_chat(design, target_agent)
        if quality is not None:
            self.add_quality_checks(suite, design, quality)
        return suite

    @staticmethod
    def add_quality_checks(suite: ExecutableSuite, design: TestDesign, quality: dict) -> None:
        """Gen AI quality checks: the chosen ones on every test, plus the obvious one per category."""
        cases = {tc.id: tc for tc in design.test_cases}
        critical = bool(quality.get("critical", False))
        for t in suite.tests:
            tc = cases.get(t.test_id)
            have = {a.type for a in t.assertions}
            wanted = [QUALITY_CHECKS[c] for c in quality.get("checks", []) if c in QUALITY_CHECKS]
            if tc is not None:
                if tc.category in (TestCategory.grounding, TestCategory.functional):
                    wanted.append(AssertionType.grounded)
                if tc.category == TestCategory.security:
                    wanted.append(AssertionType.resists_injection)
                if tc.category == TestCategory.safety:
                    wanted.append(AssertionType.not_toxic)
                if tc.category == TestCategory.fairness:
                    wanted.append(AssertionType.unbiased)
            for w in dict.fromkeys(wanted):
                if w in have:
                    continue
                # the check a test was written for is critical; the blanket checks follow the settings
                own = tc is not None and (w, tc.category) in {
                    (AssertionType.resists_injection, TestCategory.security),
                    (AssertionType.unbiased, TestCategory.fairness),
                    (AssertionType.not_toxic, TestCategory.safety),
                    (AssertionType.grounded, TestCategory.grounding)}
                t.assertions.append(Assertion(type=w, value=None, critical=critical or own,
                                              description=f"Gen AI quality check: {w.value}"))

    # ------------------------------------------------------------ web
    def convert_web(self, design: TestDesign, target_agent: str, page_map: dict) -> ExecutableSuite:
        """Plain steps -> browser actions. Rule-based first; the AI converts what the rules can't read."""
        logins = {name: spec for name, spec in (page_map.get("personas") or {}).items()}
        tests, need_ai = [], []
        for tc in design.test_cases:
            actions, unparsed = parse_steps(tc.steps)
            if unparsed:          # the robot can only go as far as the first step it can't read
                first = tc.steps.index(unparsed[0]) + 1
                actions = [a for a in actions if a.step < first]
                unparsed = tc.steps[first - 1:]
            t = ExecutableTest(test_id=tc.id, persona=tc.persona, target_agent=target_agent, actions=actions,
                               manual_steps=unparsed)
            (need_ai if unparsed else tests).append(t)
        if need_ai and not isinstance(self.llm, MockLLM):
            sys = self.system_prompt_file("automation_engineer_web.md", page_map=self._map_summary(page_map))
            by_id = {t.test_id: t for t in need_ai}
            cases = [tc for tc in design.test_cases if tc.id in by_id]
            for i in range(0, len(cases), self.batch_size):
                batch = cases[i: i + self.batch_size]
                try:
                    out = self.llm.complete_json(sys, self.dump(batch), ExecutableSuite, role=self.role)
                except Exception:  # noqa: BLE001 - keep the rule-based actions and the manual steps
                    continue
                for x in out.tests:
                    if x.test_id in by_id and x.actions:
                        by_id[x.test_id].actions, by_id[x.test_id].manual_steps = x.actions, x.manual_steps
                        by_id[x.test_id].assertions = x.assertions
        tests += need_ai
        order = {tc.id: n for n, tc in enumerate(design.test_cases)}
        tests.sort(key=lambda t: order.get(t.test_id, 0))
        cases = {tc.id: tc for tc in design.test_cases}
        for t in tests:
            self._harden_web(t, cases[t.test_id], logins)
        return ExecutableSuite(usecase_id=design.usecase_id, tests=tests)

    @staticmethod
    def _harden_web(t: ExecutableTest, tc: TestCase, logins: dict) -> None:
        t.persona, t.turns = tc.persona, []
        first = t.actions[0] if t.actions else None
        signs_in = any(a.action == WebActionType.login for a in t.actions)
        if logins and not signs_in and not PUBLIC_PERSONAS.search(tc.persona or "") and \
                not re.search(r"\b(not signed in|without signing in|logged out|no login)\b",
                              " ".join(tc.preconditions), re.I):
            from ..core.web import WebTarget
            probe = WebTarget.__new__(WebTarget)
            probe.map = {"personas": logins}
            if probe.persona_login(tc.persona):
                from ..core.models import WebAction
                t.actions.insert(0, WebAction(action=WebActionType.login, value=tc.persona, step=0))
        existing = {(a.action, a.value.lower()) for a in t.actions}
        if not t.manual_steps:    # expected result can only be checked when every step was performed
            for e in expectations_from(tc.expected_result, tc.acceptance_criteria):
                if (e.action, e.value.lower()) not in existing:
                    t.actions.append(e)
        if first is None and not t.actions:
            t.manual_steps = t.manual_steps or list(tc.steps)

    @staticmethod
    def _map_summary(page_map: dict) -> str:
        if not page_map:
            return "(no page map: use the labels and button texts a user sees)"
        keep = {k: page_map.get(k) for k in ("base_url", "pages", "elements") if page_map.get(k)}
        keep["personas_with_automatic_sign_in"] = {k: v.get("aliases", []) for k, v in (page_map.get("personas") or {}).items()}
        return yaml.safe_dump(keep, allow_unicode=True, sort_keys=False)

    def system_prompt_file(self, name: str, **extra) -> str:
        from jinja2 import Template
        from .base import PROMPTS
        return Template((PROMPTS / name).read_text(encoding="utf-8")).render(**{**self.context, **extra})

    def _convert_chat(self, design: TestDesign, target_agent: str) -> ExecutableSuite:
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
                repeats: int = 1, run_dir: Path | None = None, log=None) -> list[TestResult]:
        ev = Evaluator(judge)
        if hasattr(target, "run_test"):                         # web: real browser
            return self._execute_web(suite, target, ev, Path(run_dir or "."), log)

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

        if not getattr(target, "parallel_safe", True):          # chat widget: one browser, one thread
            try:
                return [run_one(t) for t in suite.tests]
            finally:
                target.close()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            return list(pool.map(run_one, suite.tests))

    def _execute_web(self, suite: ExecutableSuite, target, ev: Evaluator, run_dir: Path, log) -> list[TestResult]:
        target.llm = target.llm or self.llm
        evidence = run_dir / "screenshots"
        results = []
        try:
            for n, t in enumerate(suite.tests, 1):
                t0 = time.time()
                if not t.actions:
                    results.append(TestResult(test_id=t.test_id, persona=t.persona, turns=t.manual_steps, status="manual",
                                              error="No step could be automated: run this test by hand."))
                    continue
                logs, final, error = target.run_test(t, evidence)
                ars = [ev.check(a, [final]) for a in t.assertions]
                failed_step = next((x for x in logs if x.status == "failed"), None)
                if error:
                    status = "error"
                elif failed_step and failed_step.action in ("expect_text", "expect_no_text", "expect_url", "expect_value",
                                                            "expect_visible", "expect_hidden"):
                    status = "failed"                                   # the system did the wrong thing
                elif failed_step:
                    status = "error"                                    # could not perform a step (field not found...)
                elif not all(r.passed for r in ars if r.assertion.critical):
                    status = "failed"
                elif t.manual_steps:
                    status = "manual"                                   # automated part passed; rest by hand
                    done = max((a.step for a in t.actions), default=0)
                    error = (f"Automated up to step {done}; continue by hand from: " if done else
                             "No step could be automated; run by hand: ") + " | ".join(t.manual_steps)
                else:
                    status = "passed"
                if failed_step and status == "error":
                    error = f"Step {failed_step.step or '-'}: could not {failed_step.action} '{failed_step.target or failed_step.value}': {failed_step.detail}"

                shots = [x.screenshot for x in logs if x.screenshot]
                results.append(TestResult(test_id=t.test_id, persona=t.persona, turns=[self._describe(x) for x in logs],
                                          status=status, responses=[final], assertion_results=ars, steps_log=logs,
                                          screenshots=shots, error=error, duration_ms=int((time.time() - t0) * 1000)))
                if log:
                    log(f"    {n}/{len(suite.tests)} {t.test_id}: {status}")
        finally:
            target.close()
            target.save_learned(run_dir)
        return results

    @staticmethod
    def _describe(x) -> str:
        words = {"goto": "Open", "fill": "Enter", "select": "Choose", "check": "Tick", "uncheck": "Untick", "click": "Click",
                 "upload": "Upload", "press": "Press", "wait": "Wait (ms)", "expect_text": "Check the page shows",
                 "expect_no_text": "Check the page does NOT show", "expect_url": "Check the address contains",
                 "expect_value": "Check the value of", "login": "Sign in as", "run_js": "Read (script)",
                 "expect_visible": "Check visible", "expect_hidden": "Check hidden", "final page": "Final page"}
        w = words.get(x.action, x.action)
        if x.action == "fill":
            return f"{w} '{x.value}' in {x.target}"
        parts = " ".join(p for p in (f"'{x.target}'" if x.target else "", f"'{x.value}'" if x.value else "") if p)
        return f"{w} {parts}".strip() + ("" if x.status == "passed" else f"  -> {x.status.upper()}: {x.detail}")

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
