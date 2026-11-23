"""One API used by both the command line and the web page.

    preview(inputs)            -> read + split documents, no AI calls
    run_batch(preview, ...)    -> run the four agents for each selected scenario

Developers integrating agentic-qa elsewhere (a CI job, another UI, a chat bot)
should call these two functions rather than the CLI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import yaml

from .core.models import Gap, GapType, UseCase
from .ingest.model import Conflict, IngestResult
from .ingest.pipeline import IngestError, IngestPipeline, render_document_text, render_report
from .orchestrator import Pipeline, load_usecase


@dataclass
class Preview:
    batch_dir: Path
    result: IngestResult
    report_md: str
    reference_text: str = ""

    @property
    def ok(self) -> bool:
        return self.result.report.ok_to_continue


@dataclass
class BatchOutcome:
    batch_dir: Path
    runs: list[dict] = field(default_factory=list)
    workbook: Optional[Path] = None


def load_settings(settings_path: str = "config/settings.yaml") -> dict:
    return yaml.safe_load(Path(settings_path).read_text(encoding="utf-8"))


def make_ingest(settings: dict, profile: Optional[str] = None, log=print) -> IngestPipeline:
    ing = settings.get("ingest", {}) or {}
    return IngestPipeline(profile=profile or ing.get("profile"), plugins=ing.get("plugins"),
                          source_settings=settings.get("sources", {}), log=log)


def is_legacy_single_usecase(inputs: list[str]) -> bool:
    """A single short .md/.txt use case (the original format) runs without the ingest stage."""
    if len(inputs) != 1:
        return False
    p = Path(inputs[0])
    return p.is_file() and p.suffix.lower() in (".md", ".txt") and p.stat().st_size < 20_000


def preview(inputs: list[str], settings_path: str = "config/settings.yaml", profile: Optional[str] = None,
            references: Optional[list[str]] = None, batch_dir: Optional[Path] = None, log=print) -> Preview:
    settings = load_settings(settings_path)
    root = Path(settings.get("paths", {}).get("runs", "runs"))
    batch_dir = batch_dir or root / f"batch_{datetime.now():%Y%m%d_%H%M%S}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    ingest = make_ingest(settings, profile, log)
    log(f"[Reader] Reading {len(inputs)} input(s) ...")
    result = ingest.run(inputs, batch_dir)
    ref_text = ""
    if references:
        log(f"[Reader] Reading {len(references)} reference document(s) ...")
        ref_result = ingest.run(references, batch_dir / "references", save=False)
        ref_text = render_document_text(ref_result)
    report = render_report(result)
    r = result.report
    log(f"    {len(result.documents)} document(s), {len(result.packages)} use case(s), "
        f"{len(r.conflicts)} conflict(s), confidence {r.confidence.upper()}")
    return Preview(batch_dir=batch_dir, result=result, report_md=report, reference_text=ref_text)


def conflicts_as_gaps(conflicts: list[Conflict]) -> list[Gap]:
    return [Gap(id=c.id, type=GapType.contradiction, description=c.description,
                impact="Test cases may assert the wrong expected value; at least one source is wrong or outdated."
                if c.confidence == "high" else "Possible contradiction (detected heuristically); please confirm.",
                question_for_ba=c.question,
                assumed_resolution="Tests use the BRS / newest wording where possible; marked as dependent on this gap.")
            for c in conflicts]


def run_batch(pv: Preview, settings_path: str = "config/settings.yaml", scenarios: Optional[list[str]] = None,
              until: str = "report", force: bool = False, review_gate=None, log: Callable = print,
              app: Optional[str] = None, headed: Optional[bool] = None) -> BatchOutcome:
    if not pv.ok and not force:
        raise IngestError("Ingest confidence is LOW, so the agents were not started. Check the preview, fix the "
                          "client profile, or re-run with force.")
    known = [p.scenario.key for p in pv.result.packages]
    if scenarios and (unknown := [s for s in scenarios if s not in known]):
        raise IngestError(f"Unknown scenario key(s) {unknown}. Found: {known}")
    pipe = Pipeline(settings_path, log=log, app=app, headed=headed)
    out = BatchOutcome(batch_dir=pv.batch_dir)
    for pkg in pv.result.packages:
        if scenarios and pkg.scenario.key not in scenarios:
            continue
        uc = UseCase(id=pkg.scenario.key, title=pkg.scenario.name, text=pkg.text, source=str(pv.batch_dir))
        run_dir = pv.batch_dir / pkg.scenario.key
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "00_usecase.md").write_text(pkg.text, encoding="utf-8")
        log(f"\n=== {uc.id}: {uc.title}  ->  {run_dir}")
        s = pipe.run(run_dir, uc, stop=until, reference_docs=pv.reference_text, review_gate=review_gate,
                     extra_gaps=conflicts_as_gaps(pkg.conflicts))
        s["scenario"] = pkg.scenario.key
        out.runs.append(s)
    out.workbook = export_excel(pv.batch_dir, settings_path, log)
    return out


def export_excel(path: Path, settings_path: str = "config/settings.yaml", log: Callable = print) -> Optional[Path]:
    """(Re)build the Excel workbook(s) for a run folder or a batch folder."""
    from .export.excel import export_batch, export_run

    p = load_settings(settings_path).get("paths", {})
    kw = dict(skeleton_path=p.get("skeleton", "config/testcase_skeleton.yaml"),
              glossary_path=p.get("glossary", "config/glossary.yaml"))
    path = Path(path)
    try:
        if (path / "02_testcases.json").exists():
            out = export_run(path, **kw)
        else:
            for d in sorted(path.glob("SCN-*")):
                if (d / "02_testcases.json").exists():
                    export_run(d, **kw)
            out = export_batch(path, **kw)
        if out:
            log(f"\nExcel workbook: {out}")
        return out
    except Exception as e:  # noqa: BLE001
        log(f"WARNING: could not write the Excel workbook: {e}")
        return None


def run_legacy(usecase_path: str, settings_path: str = "config/settings.yaml", until: str = "report",
               reference_text: str = "", review_gate=None, log: Callable = print, app: Optional[str] = None,
               headed: Optional[bool] = None) -> dict:
    pipe = Pipeline(settings_path, log=log, app=app, headed=headed)
    uc = load_usecase(Path(usecase_path))
    rd = pipe.new_run_dir(uc)
    log(f"\n=== {uc.id}: {uc.title}  ->  {rd}")
    return pipe.run(rd, uc, stop=until, reference_docs=reference_text, review_gate=review_gate)


def run_testcases(testcases: str, settings_path: str = "config/settings.yaml", app: Optional[str] = None,
                  headed: Optional[bool] = None, until: str = "report", log: Callable = print) -> dict:
    """Execute existing test cases (02_testcases.json from an earlier run, or a hand-written file in the
    same format) against the chosen application: Automation Engineer + Defect Manager only."""
    import json as _json
    from datetime import datetime

    from .core.models import TestDesign, UseCaseUnderstanding

    src = Path(testcases)
    if src.is_dir():
        src = src / "02_testcases.json"
    if not src.exists():
        raise IngestError(f"Test-case file not found: {src}")
    design = TestDesign.model_validate_json(src.read_text(encoding="utf-8"))
    pipe = Pipeline(settings_path, log=log, app=app, headed=headed)
    root = Path(load_settings(settings_path).get("paths", {}).get("runs", "runs"))
    run_dir = root / f"{design.usecase_id}_{pipe.app}_{datetime.now():%Y%m%d_%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=True)
    und_src = src.parent / "01_understanding.json"
    if und_src.exists():
        und = UseCaseUnderstanding.model_validate_json(und_src.read_text(encoding="utf-8"))
    else:
        und = UseCaseUnderstanding(usecase_id=design.usecase_id, summary=design.coverage_notes or design.usecase_id,
                                   target_agent=pipe.app, personas=sorted({t.persona for t in design.test_cases}),
                                   user_intents=[], business_rules=[], knowledge_sources=[])
    (run_dir / "01_understanding.json").write_text(und.model_dump_json(indent=2), encoding="utf-8")
    (run_dir / "02_testcases.json").write_text(_json.dumps(design.model_dump(mode="json"), indent=2, ensure_ascii=False),
                                               encoding="utf-8")
    log(f"\n=== {design.usecase_id}: {len(design.test_cases)} test cases  ->  {run_dir}")
    return pipe.run(run_dir, start="automate", stop=until)


def make_troubleshooter(batch_dir: Path, settings_path: str = "config/settings.yaml", profile: Optional[str] = None):
    """The Requirement Troubleshooter for one batch (documents read by preview, plus any generated tests)."""
    from .core.llm import build_llm
    from .troubleshoot.agent import Troubleshooter
    from .troubleshoot.index import RequirementIndex

    settings = load_settings(settings_path)
    llm_cfg = {**settings["llm"], **(settings.get("llm_overrides") or {}).get("troubleshooter", {})}
    idx = RequirementIndex.load(Path(batch_dir), profile or (settings.get("ingest") or {}).get("profile"))
    return Troubleshooter(build_llm(llm_cfg), idx)
