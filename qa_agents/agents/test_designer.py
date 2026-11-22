from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml

from ..core.llm import MockLLM
from ..core.models import TestDesign, UseCaseUnderstanding
from .base import BaseAgent
from .design_quality import DesignIssue, check_design, quality_report, sort_and_renumber


class TestDesigner(BaseAgent):
    __test__ = False  # tell pytest this is not a test class
    """Test Designer: understanding -> test cases (in the org's skeleton) + gap report."""

    role = "test_designer"
    prompt_file = "test_designer.md"

    def __init__(self, llm, context=None, skeleton_path: str = "config/testcase_skeleton.yaml",
                 glossary_path: str = "config/glossary.yaml"):
        super().__init__(llm, context)
        self.skeleton = yaml.safe_load(Path(skeleton_path).read_text(encoding="utf-8"))
        g = Path(glossary_path)
        gl = yaml.safe_load(g.read_text(encoding="utf-8")) if g.exists() else {}
        self.glossary: dict = gl.get("terms") or {}
        self.common: list = gl.get("common") or []
        self.last_issues: list[DesignIssue] = []
        self.context.setdefault("system_kind", "a conversational AI agent (chatbot / assistant)")

    @property
    def conversational(self) -> bool:
        return str(self.context.get("system_kind", "")).startswith("a conversational")

    def _skeleton_text(self) -> str:
        lines = []
        for col in self.skeleton["columns"]:
            src = col["field"]
            kind = "custom -> put in extra." + src.split(".", 1)[1] if src.startswith("extra.") else f"core field `{src}`"
            lines.append(f"- **{col['name']}** ({kind}): {col.get('description', '')}")
        return "\n".join(lines)

    def run(self, understanding: UseCaseUnderstanding) -> TestDesign:
        sys = self.system_prompt(skeleton=self._skeleton_text(),
                                 glossary="\n".join(f"- {k}: {v}" for k, v in self.glossary.items()) or "(none)",
                                 common_terms=", ".join(self.common) or "none")
        out = self.llm.complete_json(sys, self.dump(understanding), TestDesign, role=self.role)
        self._stamp(out, understanding.usecase_id)
        issues = self.check(out)
        if issues and not isinstance(self.llm, MockLLM):
            out = self._repair(sys, understanding, out, issues)
            issues = self.check(out)
        self.last_issues = issues
        return sort_and_renumber(out)

    def check(self, design: TestDesign) -> list[DesignIssue]:
        return check_design(design, self.glossary, self.common, self.conversational)

    @staticmethod
    def _stamp(design: TestDesign, usecase_id: str) -> None:
        design.usecase_id = usecase_id
        for tc in design.test_cases:
            tc.usecase_id = usecase_id

    def _repair(self, sys: str, understanding, design: TestDesign, issues: list[DesignIssue]) -> TestDesign:
        """One review round: the reviewer's findings go back to the Test Designer."""
        bad = {i.test_id for i in issues if i.test_id != "*"}
        suite = [str(i) for i in issues if i.test_id == "*"]
        payload = {
            "review_findings": [str(i) for i in issues],
            "test_cases_to_fix": [t.model_dump(mode="json") for t in design.test_cases if t.id in bad],
            "existing_test_titles": [f"{t.id} [{t.priority.value}, {t.perspective.value}] {t.title}"
                                     for t in design.test_cases],
        }
        instr = ("A reviewer checked your test cases. Return a JSON TestDesign whose test_cases contain ONLY: "
                 "(a) the corrected versions of `test_cases_to_fix` (keep their ids), and "
                 + ("(b) NEW test cases (new ids) that fix these coverage findings: " + "; ".join(suite) + ". "
                    if suite else "")
                 + "Do not repeat test cases that need no change. gaps may be empty.")
        try:
            fix = self.llm.complete_json(sys, instr + "\n\n" + self.dump(payload), TestDesign, role=self.role)
        except Exception:  # noqa: BLE001 - keep the first version if the repair call fails
            return design
        by_id = {t.id: t for t in design.test_cases}
        returned: set[str] = set()
        for n, t in enumerate(fix.test_cases, 1):
            t.usecase_id = design.usecase_id
            # a corrected test keeps its id once; any other test reusing an existing id is a new test
            if t.id in returned or (t.id in by_id and t.id not in bad):
                t.id = f"{t.id}-NEW{n}"
            returned.add(t.id)
            by_id[t.id] = t
        design.test_cases = list(by_id.values())
        known = {g.id for g in design.gaps}
        design.gaps += [g for g in fix.gaps if g.id not in known]
        return design

    def export_quality(self, design: TestDesign, path: Path) -> None:
        path.write_text(quality_report(design, self.last_issues), encoding="utf-8")
        path.with_suffix(".json").write_text(json.dumps([str(i) for i in self.last_issues], indent=1), encoding="utf-8")

    # ---------------------------------------------------------- exports
    def export_csv(self, design: TestDesign, path: Path) -> None:
        cols = self.skeleton["columns"]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM: opens cleanly in Excel
            w = csv.writer(f)
            w.writerow([c["name"] for c in cols])
            for tc in design.test_cases:
                d = tc.model_dump(mode="json")
                row = []
                for c in cols:
                    field = c["field"]
                    v = d.get("extra", {}).get(field[6:], "") if field.startswith("extra.") else d.get(field, "")
                    if isinstance(v, list):
                        v = "\n".join(f"{i}. {x}" for i, x in enumerate(v, 1)) if field in ("steps",) else "\n".join(map(str, v))
                    row.append(v if v is not None else "")
                w.writerow(row)

    @staticmethod
    def export_gaps(design: TestDesign, path: Path) -> None:
        lines = [f"# Gap report: {design.usecase_id}\n",
                 "Review these with the BA. Tests marked with a gap id depend on the assumption shown.\n",
                 "| ID | Type | Gap | Impact | Question for BA | Assumed for now | Dependent tests |",
                 "|---|---|---|---|---|---|---|"]
        for g in design.gaps:
            deps = ", ".join(t.id for t in design.test_cases if t.based_on_assumption == g.id) or "-"
            cells = [g.id, g.type.value, g.description, g.impact, g.question_for_ba, g.assumed_resolution, deps]
            lines.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
        if design.coverage_notes:
            lines += ["", "## Coverage notes", design.coverage_notes]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
