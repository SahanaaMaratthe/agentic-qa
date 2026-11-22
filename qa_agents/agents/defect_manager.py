from __future__ import annotations

from pathlib import Path

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
        failed = [r for r in results if r.status in ("failed", "error", "flaky")]
        analyses: dict[str, FailureAnalysis] = {}
        for i in range(0, len(failed), self.batch_size):
            batch = failed[i : i + self.batch_size]
            payload = [{
                "test_case": cases[r.test_id].model_dump(mode="json") if r.test_id in cases else {},
                "status": r.status, "error": r.error,
                "conversation": [{"user": u, "agent": (r.responses[j].text if j < len(r.responses) else None),
                                  "citations": [c.title for c in r.responses[j].citations] if j < len(r.responses) else []}
                                 for j, u in enumerate(r.turns)],
                "failed_checks": [f"{a.assertion.type.value}({a.assertion.value}): {a.detail}"
                                  for a in r.assertion_results if not a.passed],
            } for r in batch]
            out = self.llm.complete_json(self.system_prompt(), self.dump(payload), FailureAnalysisBatch, role=self.role)
            ids = {r.test_id for r in batch}
            for a in out.analyses:
                if a.test_id in ids:
                    analyses[a.test_id] = a
        for r in failed:  # anything the LLM skipped still gets surfaced
            if r.test_id not in analyses:
                analyses[r.test_id] = FailureAnalysis(
                    test_id=r.test_id,
                    classification=BugClassification.environment if r.status == "error" else BugClassification.needs_review,
                    title=f"{r.test_id} {r.status}", severity="Medium", suspected_root_cause="unknown",
                    summary=r.error or "Not analysed by LLM")
        return [analyses[r.test_id] for r in failed]

    def build_reports(self, analyses: list[FailureAnalysis], results: list[TestResult], design: TestDesign,
                      fileable: set[str]) -> list[BugReport]:
        """Evidence fields come from the actual run, never from the LLM."""
        res = {r.test_id: r for r in results}
        cases: dict[str, TestCase] = {tc.id: tc for tc in design.test_cases}
        bugs = []
        for n, a in enumerate((x for x in analyses if x.classification.value in fileable), 1):
            r, tc = res[a.test_id], cases.get(a.test_id)
            steps = [f"Sign in to the agent as persona **{r.persona}**"] + [f'Send: "{t}"' for t in r.turns]
            actual = "\n\n".join(f"Turn {i+1}: {resp.text}" for i, resp in enumerate(r.responses)) or r.error
            bugs.append(BugReport(
                id=f"BUG-{design.usecase_id}-{n:03d}", title=a.title, severity=a.severity,
                classification=a.classification, suspected_root_cause=a.suspected_root_cause,
                usecase_id=design.usecase_id, test_ids=[a.test_id], persona=r.persona, steps_to_reproduce=steps,
                expected=(tc.expected_result + "\n\n" + "\n".join(f"- {c}" for c in tc.acceptance_criteria)) if tc else "",
                actual=actual,
                failed_checks=[f"{x.assertion.type.value}: {x.detail}" for x in r.assertion_results if not x.passed] or [r.error],
                citations_returned=sorted({c.title or c.uri for resp in r.responses for c in resp.citations}),
                summary=a.summary, recommendation=a.recommendation,
                labels=[design.usecase_id, a.suspected_root_cause.replace(" ", "-")[:40], r.persona],
            ))
        return bugs

    @staticmethod
    def publish(bugs: list[BugReport], tracker: BugTracker, out_dir: Path, file_bugs: bool) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for b in bugs:
            if file_bugs:
                b.tracker_key = tracker.create(b)
            (out_dir / f"{b.id}.md").write_text(render_markdown(b), encoding="utf-8")

    @staticmethod
    def triage_md(analyses: list[FailureAnalysis]) -> str:
        lines = ["# Failure triage", "", "| Test | Classification | Severity | Root cause | Title | Recommendation |",
                 "|---|---|---|---|---|---|"]
        order = {"product_bug": 0, "needs_review": 1, "test_defect": 2, "environment": 3}
        for a in sorted(analyses, key=lambda x: order.get(x.classification.value, 9)):
            lines.append(f"| {a.test_id} | {a.classification.value} | {a.severity} | {a.suspected_root_cause} | "
                         f"{a.title} | {a.recommendation.replace('|', '/')} |")
        return "\n".join(lines) + "\n"
