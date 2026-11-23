from __future__ import annotations

from pathlib import Path

import os
import re

from ..core.models import (BugClassification, BugReport, FailureAnalysis, FailureAnalysisBatch, TestCase,
                           TestDesign, TestResult)
from ..core.tracker import BugTracker, render_markdown
from .base import BaseAgent


class DefectManager(BaseAgent):
    """Defect Manager: failed results -> triaged bug reports -> (optionally) tracker tickets."""

    role = "defect_manager"
    prompt_file = "defect_manager.md"
    batch_size = 10

    def analyse(self, results: list[TestResult], design: TestDesign) -> list[FailureAnalysis]:
        cases = {tc.id: tc for tc in design.test_cases}
        failed = [r for r in results if r.status in ("failed", "error", "flaky")]   # "manual" = not run: no triage
        analyses: dict[str, FailureAnalysis] = {}
        for i in range(0, len(failed), self.batch_size):
            batch = failed[i : i + self.batch_size]
            payload = [self._evidence(r, cases) for r in batch]
            out = self.llm.complete_json(self.system_prompt(), self.dump(payload), FailureAnalysisBatch, role=self.role)
            ids = {r.test_id for r in batch}
            for a in out.analyses:
                if a.test_id in ids:
                    analyses[a.test_id] = a
        for r in failed:  # anything the LLM skipped still gets surfaced
            if r.test_id not in analyses:
                tc = cases.get(r.test_id)
                bad = next((x for x in r.steps_log if x.status == "failed"), None)
                what = (f"{bad.action} '{bad.target or bad.value}': {bad.detail}" if bad else
                        "; ".join(f"{a.assertion.type.value}: {a.detail}" for a in r.assertion_results if not a.passed))
                analyses[r.test_id] = FailureAnalysis(
                    test_id=r.test_id,
                    classification=BugClassification.environment if r.status == "error" else BugClassification.needs_review,
                    title=(f"{'Could not run' if r.status == 'error' else 'Failed'}: {tc.title}" if tc else f"{r.test_id} {r.status}"),
                    severity=(tc.priority.value if tc and r.status != "error" else "Medium"),
                    suspected_root_cause="unknown (not analysed by AI)",
                    summary=(r.error or what or "Not analysed by the AI (offline mode).")[:600],
                    recommendation="Review the screenshot and the failed check; confirm against the requirement." if bad else "")
        return [analyses[r.test_id] for r in failed]

    @staticmethod
    def _evidence(r: TestResult, cases: dict) -> dict:
        base = {"test_case": cases[r.test_id].model_dump(mode="json") if r.test_id in cases else {},
                "status": r.status, "error": r.error,
                "failed_checks": [f"{a.assertion.type.value}({a.assertion.value}): {a.detail}"
                                  for a in r.assertion_results if not a.passed]}
        if r.steps_log:                                   # web application: what the browser did and saw
            base["application"] = "web"
            base["browser_steps"] = [f"{x.action} {x.target} {x.value}".strip() + f" -> {x.status}"
                                     + (f": {x.detail}" if x.detail else "") for x in r.steps_log if x.action != "final page"]
            base["final_page_url"] = r.responses[-1].url if r.responses else ""
            base["final_page_text"] = (r.responses[-1].text if r.responses else "")[:2500]
            return base
        base["conversation"] = [{"user": u, "agent": (r.responses[j].text if j < len(r.responses) else None),
                                 "citations": [c.title for c in r.responses[j].citations] if j < len(r.responses) else []}
                                for j, u in enumerate(r.turns)]
        return base

    def build_reports(self, analyses: list[FailureAnalysis], results: list[TestResult], design: TestDesign,
                      fileable: set[str]) -> list[BugReport]:
        """Evidence fields come from the actual run, never from the LLM."""
        res = {r.test_id: r for r in results}
        cases: dict[str, TestCase] = {tc.id: tc for tc in design.test_cases}
        bugs = []
        for n, a in enumerate((x for x in analyses if x.classification.value in fileable), 1):
            r, tc = res[a.test_id], cases.get(a.test_id)
            attachments: list[str] = []
            if r.steps_log:                                    # web: the tester's steps + where it broke
                bad = next((x for x in r.steps_log if x.status == "failed"), None)
                public = re.search(r"\b(visitor|public|guest|anonymous|not signed in)\b", r.persona, re.I)
                steps = [] if public else [f"Sign in as **{r.persona}**"]
                steps += [s for s in (tc.steps if tc else r.turns)]
                actual = self._plain(bad) if bad else (r.error or "; ".join(x.detail for x in r.assertion_results
                                                                             if not x.passed))
                if r.responses and r.responses[-1].url:
                    actual += f"\n\nPage: {r.responses[-1].url}"
                attachments = [x for x in ([bad.screenshot] if bad and bad.screenshot else [])
                               + [s for s in r.screenshots if s.endswith("final.png")] if x]
            else:
                steps = [f"Sign in to the agent as persona **{r.persona}**"] + [f'Send: "{t}"' for t in r.turns]
                actual = "\n\n".join(f"Turn {i+1}: {resp.text}" for i, resp in enumerate(r.responses)) or r.error
            bugs.append(BugReport(
                id=f"BUG-{design.usecase_id}-{n:03d}", title=a.title, severity=a.severity,
                classification=a.classification, suspected_root_cause=a.suspected_root_cause,
                usecase_id=design.usecase_id, test_ids=[a.test_id], persona=r.persona, steps_to_reproduce=steps,
                expected=(tc.expected_result + "\n\n" + "\n".join(f"- {c}" for c in tc.acceptance_criteria)) if tc else "",
                actual=actual,
                failed_checks=([self._plain(x) for x in r.steps_log if x.status == "failed"]
                               + [f"{x.assertion.type.value}: {x.detail}" for x in r.assertion_results if not x.passed]
                               ) or [r.error],
                citations_returned=sorted({c.title or c.uri for resp in r.responses for c in resp.citations}),
                summary=a.summary, recommendation=a.recommendation,
                labels=[design.usecase_id, a.suspected_root_cause.replace(" ", "-")[:40], r.persona.replace(" ", "-")[:40]],
                attachments=list(dict.fromkeys(attachments)),
            ))
        return bugs

    @staticmethod
    def _plain(x) -> str:
        """A failed browser step in words a business user understands."""
        where = f"Step {x.step}" if x.step else "Final check"
        if x.action == "expect_text":
            return f"{where}: the page should show '{x.value}', but it does not."
        if x.action == "expect_no_text":
            return f"{where}: the page should NOT show '{x.value}', but it does."
        if x.action == "expect_url":
            return f"{where}: the address should contain '{x.value}'. {x.detail}"
        return f"{where}: could not {x.action} '{x.target or x.value}'. {x.detail}"

    @staticmethod
    def publish(bugs: list[BugReport], tracker: BugTracker, out_dir: Path, file_bugs: bool) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for b in bugs:
            if file_bugs:
                b.tracker_key = tracker.create(b)
            local = b.model_copy(update={"attachments": [os.path.relpath(a, out_dir) for a in b.attachments]})
            (out_dir / f"{b.id}.md").write_text(render_markdown(local), encoding="utf-8")

    @staticmethod
    def triage_md(analyses: list[FailureAnalysis]) -> str:
        lines = ["# Failure triage", "", "| Test | Classification | Severity | Root cause | Title | Recommendation |",
                 "|---|---|---|---|---|---|"]
        order = {"product_bug": 0, "needs_review": 1, "test_defect": 2, "environment": 3}
        for a in sorted(analyses, key=lambda x: order.get(x.classification.value, 9)):
            lines.append(f"| {a.test_id} | {a.classification.value} | {a.severity} | {a.suspected_root_cause} | "
                         f"{a.title} | {a.recommendation.replace('|', '/')} |")
        return "\n".join(lines) + "\n"
