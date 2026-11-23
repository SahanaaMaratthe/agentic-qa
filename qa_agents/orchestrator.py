"""Pipeline: Requirement Analyst (understand) -> Test Designer (design + gaps) -> Automation Engineer (automate + execute) -> Defect Manager (triage + report).

Each stage reads/writes JSON artifacts in a run folder, so you can:
  * stop after B, let a human edit 02_testcases.json, then resume from C
  * re-run only C+D nightly against an approved test suite
  * replace any agent with a different implementation
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import yaml

from .agents.requirement_analyst import RequirementAnalyst
from .agents.test_designer import TestDesigner
from .agents.automation_engineer import AutomationEngineer
from .agents.defect_manager import DefectManager
from .core.apps import APP_TYPES, SYSTEM_KIND, app_kind, is_ai_app, resolve_app
from .core.llm import build_llm
from .core.models import (ExecutableSuite, FailureAnalysis, TestDesign, TestResult, UseCase,
                          UseCaseUnderstanding)
from .core.target import build_target
from .core.tracker import build_tracker

STAGES = ["analyze", "design", "automate", "execute", "report"]


def load_usecase(path: Path) -> UseCase:
    text = path.read_text(encoding="utf-8").strip()
    m = re.match(r"#\s*([A-Za-z]+-[\w-]+)\s*[:\-]\s*(.+)", text.splitlines()[0])
    uc_id, title = (m.group(1), m.group(2).strip()) if m else (path.stem, path.stem)
    return UseCase(id=uc_id, title=title, text=text, source=str(path))


class Pipeline:
    def __init__(self, settings_path: str = "config/settings.yaml", log=print, app: str | None = None,
                 headed: bool | None = None):
        """app: override the application type for this run (web, chatbot, gemini_enterprise, genai, mock, none).
        headed: True = show the browser window, False = hidden; None = as in settings."""
        self.cfg = yaml.safe_load(Path(settings_path).read_text(encoding="utf-8"))
        self.log = log
        self.target_cfg = resolve_app(self.cfg, app)
        if headed is not None:
            self.target_cfg["headless"] = not headed
        self.app = self.target_cfg["app"]
        self.kind = app_kind(self.target_cfg)
        p = self.cfg.get("paths", {})
        domain = Path(p.get("domain_context", "config/domain_context.md")).read_text(encoding="utf-8")
        personas = Path(p.get("personas", "config/personas.yaml")).read_text(encoding="utf-8")
        self.context = {"domain_context": domain, "personas": personas,
                        "system_kind": SYSTEM_KIND.get(self.app, SYSTEM_KIND["chatbot"]), "app": self.app}
        base_llm = self.cfg["llm"]
        over = self.cfg.get("llm_overrides") or {}
        llm_for = lambda role: build_llm({**base_llm, **over.get(role, {})})  # noqa: E731
        self.a = RequirementAnalyst(llm_for("requirement_analyst"), self.context)
        self.b = TestDesigner(llm_for("test_designer"), self.context, p.get("skeleton", "config/testcase_skeleton.yaml"),
                              p.get("glossary", "config/glossary.yaml"))
        self.c = AutomationEngineer(llm_for("automation_engineer"), self.context)
        self.d = DefectManager(llm_for("defect_manager"), self.context)
        self.judge = build_llm({**base_llm, **(self.cfg.get("judge_llm") or {})})

    # ---------------------------------------------------------- helpers
    @staticmethod
    def _save(path: Path, obj) -> None:
        data = obj.model_dump(mode="json") if hasattr(obj, "model_dump") else [o.model_dump(mode="json") for o in obj]
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _load(path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def new_run_dir(self, uc: UseCase) -> Path:
        root = Path(self.cfg.get("paths", {}).get("runs", "runs"))
        d = root / f"{uc.id}_{datetime.now():%Y%m%d_%H%M%S}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _excel(self, run_dir: Path) -> None:
        p = self.cfg.get("paths", {})
        try:
            from .export.excel import export_run
            out = export_run(run_dir, skeleton_path=p.get("skeleton", "config/testcase_skeleton.yaml"),
                             glossary_path=p.get("glossary", "config/glossary.yaml"))
            self.log(f"    Excel: {out}")
        except Exception as e:  # noqa: BLE001 - a spreadsheet problem must not lose the test design
            self.log(f"    WARNING: could not write the Excel file: {e}")

    # ---------------------------------------------------------- run
    def run(self, run_dir: Path, usecase: UseCase | None = None, start: str = "analyze", stop: str = "report",
            reference_docs: str = "", review_gate=None, extra_gaps: list | None = None) -> dict:
        """extra_gaps: gaps found before the agents ran (e.g. conflicts between source documents)."""
        self.log(f"    Application under test: {APP_TYPES.get(self.app, self.app)}")
        (run_dir / "00_run.json").write_text(json.dumps({"app": self.app, "adapter": self.target_cfg.get("type")}),
                                             encoding="utf-8")
        if self.kind == "none" and STAGES.index(stop) > STAGES.index("design"):
            self.log("    app is 'none': stopping after test design (nothing to execute against).")
            stop = "design"
        todo = STAGES[STAGES.index(start) : STAGES.index(stop) + 1]
        f = lambda n: run_dir / n  # noqa: E731
        summary: dict = {"run_dir": str(run_dir)}

        if "analyze" in todo:
            self.log("[Requirement Analyst] Analysing use case ...")
            und = self.a.run(usecase, reference_docs)
            self._save(f("01_understanding.json"), und)
        und = UseCaseUnderstanding.model_validate(self._load(f("01_understanding.json")))

        if "design" in todo:
            self.log("[Test Designer] Designing test cases and gap report ...")
            design = self.b.run(und)
            if extra_gaps:
                known = {g.id for g in design.gaps}
                design.gaps.extend(g for g in extra_gaps if g.id not in known)
            self._save(f("02_testcases.json"), design)
            self.b.export_csv(design, f("02_testcases.csv"))
            self.b.export_gaps(design, f("02_gaps.md"))
            self.b.export_quality(design, f("02_quality.md"))
            self._excel(run_dir)
            self.log(f"    {len(design.test_cases)} test cases, {len(design.gaps)} gaps")
            if review_gate and not review_gate(design, run_dir):
                summary["stopped_at"] = "review"
                return summary
        design = TestDesign.model_validate(self._load(f("02_testcases.json")))

        if "automate" in todo:
            self.log("[Automation Engineer] Converting test cases to executable suite ...")
            from .core.web import load_page_map
            quality = None
            if is_ai_app(self.target_cfg):
                q = self.cfg.get("quality_checks") or {}
                quality = {"checks": q.get("checks", ["no_pii", "not_toxic"]), "critical": q.get("critical", False)}
                if q.get("enabled") is False:
                    quality = None
            suite = self.c.convert(design, und.target_agent, kind=self.kind,
                                   page_map=load_page_map(self.target_cfg.get("page_map")), quality=quality)
            self._save(f("03_executable_suite.json"), suite)
        if "execute" in todo:
            suite = ExecutableSuite.model_validate(self._load(f("03_executable_suite.json")))
            rc = self.cfg.get("run", {})
            self.log(f"[Automation Engineer] Executing {len(suite.tests)} tests on: {APP_TYPES.get(self.app, self.app)} ...")
            results = self.c.execute(suite, build_target(self.target_cfg), self.judge,
                                     concurrency=rc.get("concurrency", 4), repeats=rc.get("repeats", 1),
                                     run_dir=run_dir, log=self.log)
            self._save(f("03_results.json"), results)
            f("03_junit.xml").write_text(self.c.junit_xml(results, design.usecase_id), encoding="utf-8")
            f("03_summary.md").write_text(self.c.summary_md(results), encoding="utf-8")
            self._excel(run_dir)                       # refresh with automated Pass / Fail
            counts: dict[str, int] = {}
            for r in results:
                counts[r.status] = counts.get(r.status, 0) + 1
            summary["results"] = counts
            self.log(f"    {counts}")

        if "report" in todo:
            results = [TestResult.model_validate(x) for x in self._load(f("03_results.json"))]
            tcfg = self.cfg.get("tracker", {"type": "markdown"})
            self.log("[Defect Manager] Triaging failures ...")
            analyses = self.d.analyse(results, design)
            f("04_triage.json").write_text(json.dumps([a.model_dump(mode="json") for a in analyses], indent=2), encoding="utf-8")
            f("04_triage.md").write_text(self.d.triage_md(analyses), encoding="utf-8")
            fileable = set(tcfg.get("file_classifications", ["product_bug"]))
            bugs = self.d.build_reports(analyses, results, design, fileable)
            self.d.publish(bugs, build_tracker(tcfg), f("bugs"), file_bugs=bool(tcfg.get("file_bugs")))
            self._save(f("04_bugs.json"), bugs)
            self._excel(run_dir)                       # add triage verdicts and bug IDs
            summary["bugs"] = [{"id": b.id, "severity": b.severity, "title": b.title, "key": b.tracker_key} for b in bugs]
            self.log(f"    {len(bugs)} bug report(s) written to {f('bugs')}")
        return summary
