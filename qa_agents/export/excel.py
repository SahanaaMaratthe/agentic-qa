"""Excel workbooks of generated test cases, ready to upload to Google Drive / SharePoint.

Per use case:  <run>/02_testcases.xlsx
Per batch:     <batch>/test_cases_<batch>.xlsx   (one test-case sheet per use case)

Sheets: Summary · Test Cases · Gaps & Conflicts · Traceability (RTM) · Glossary
The test-case sheet has execution columns (Status dropdown, Actual Result, Tested By,
Test Date, Comments) so it doubles as the team's execution tracker; Status is pre-filled
from automated results when the tests were executed.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from ..core.models import PRIORITY_ORDER, Priority, TestDesign, UseCaseUnderstanding

# ------------------------------------------------------------------ styles
HEAD_FILL = PatternFill("solid", fgColor="1F4E78")
HEAD_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=14, color="1F4E78")
INPUT_FILL = PatternFill("solid", fgColor="FFF9E6")          # columns people fill in
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
PRIORITY_STYLE = {      # light fill + dark text of the same colour family
    "Critical": ("FFC7CE", "9C0006"), "High": ("FCE4D6", "843C0C"),
    "Medium": ("FFF2CC", "7F6000"), "Low": ("E2EFDA", "375623"),
}
STATUS_STYLE = {"Pass": ("C6EFCE", "006100"), "Fail": ("FFC7CE", "9C0006"), "Blocked": ("FCE4D6", "843C0C")}
STATUSES = ["Not run", "Pass", "Fail", "Blocked", "Not applicable"]
EXEC_COLS = ["Status", "Actual Result", "Tested By", "Test Date", "Comments"]
WIDTHS = {"id": 17, "usecase_id": 11, "title": 38, "purpose": 44, "perspective": 11, "category": 14, "priority": 10,
          "priority_reason": 36, "business_impact": 36, "persona": 16, "preconditions": 30, "steps": 48,
          "expected_result": 44, "acceptance_criteria": 44, "traceability": 22, "based_on_assumption": 12}


# ------------------------------------------------------------------ data from a run folder
@dataclass
class RunData:
    run_dir: Path
    usecase_id: str
    title: str
    design: TestDesign
    understanding: Optional[UseCaseUnderstanding] = None
    results: dict = field(default_factory=dict)          # test_id -> TestResult dict
    requirements: list = field(default_factory=list)     # (id, text, source)
    issues: list = field(default_factory=list)           # quality findings (strings)
    triage: dict = field(default_factory=dict)           # test_id -> Defect Manager analysis
    bugs: dict = field(default_factory=dict)             # test_id -> bug id (+ tracker key)


def load_run(run_dir: Path) -> RunData:
    run_dir = Path(run_dir)
    design = TestDesign.model_validate(json.loads((run_dir / "02_testcases.json").read_text(encoding="utf-8")))
    und = None
    if (run_dir / "01_understanding.json").exists():
        und = UseCaseUnderstanding.model_validate(json.loads((run_dir / "01_understanding.json").read_text(encoding="utf-8")))
    results = {}
    if (run_dir / "03_results.json").exists():
        results = {r["test_id"]: r for r in json.loads((run_dir / "03_results.json").read_text(encoding="utf-8"))}
    issues = []
    if (run_dir / "02_quality.json").exists():
        issues = json.loads((run_dir / "02_quality.json").read_text(encoding="utf-8"))
    triage, bugs = {}, {}
    if (run_dir / "04_triage.json").exists():
        triage = {a["test_id"]: a for a in json.loads((run_dir / "04_triage.json").read_text(encoding="utf-8"))}
    if (run_dir / "04_bugs.json").exists():
        for b in json.loads((run_dir / "04_bugs.json").read_text(encoding="utf-8")):
            for tid in b.get("test_ids", []):
                bugs[tid] = b["id"] + (f" ({b['tracker_key']})" if b.get("tracker_key") else "")
    title = und.summary if und else design.usecase_id
    uc = run_dir / "00_usecase.md"
    if uc.exists():
        first = uc.read_text(encoding="utf-8").splitlines()[0]
        title = re.sub(r"^#\s*[\w-]+:\s*", "", first).strip() or title
    return RunData(run_dir, design.usecase_id, title, design, und, results,
                   _requirements(run_dir, design.usecase_id, und), issues, triage, bugs)


def _requirements(run_dir: Path, key: str, und: Optional[UseCaseUnderstanding]) -> list:
    """Requirement IDs to trace: from the read BRD/BRS (batch runs), else from the use-case analysis."""
    items_file = run_dir.parent / "00_ingest" / "items.json"
    out, seen = [], set()
    if items_file.exists():
        for it in json.loads(items_file.read_text(encoding="utf-8")):
            iid = it.get("item_id")
            if iid and (key in it.get("scenarios", []) or "SHARED" in it.get("scenarios", [])) and iid not in seen:
                seen.add(iid)
                text = " | ".join(v for k, v in (it.get("fields") or {}).items() if v != iid) or it.get("text", "")
                src = it["ref"]["file"] + (f", sheet '{it['ref']['sheet']}'" if it["ref"].get("sheet") else "") + \
                    (f", page {it['ref']['page']}" if it["ref"].get("page") else "") + \
                    (f", row {it['ref']['row']}" if it["ref"].get("row") else "")
                out.append((iid, text, src))
        return out
    if und:
        for line in [*und.business_rules, *und.implicit_requirements]:
            m = re.match(r"^\s*([A-Za-z]{1,6}-?\d+(?:\.\d+)?)\s*[:\-]\s*(.*)", line)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                out.append((m.group(1), m.group(2), "use-case analysis"))
    return out


# ------------------------------------------------------------------ helpers
def _cell_value(tc: dict, field_name: str):
    v = tc.get("extra", {}).get(field_name[6:], "") if field_name.startswith("extra.") else tc.get(field_name, "")
    if isinstance(v, list):
        return "\n".join(f"{i}. {x}" for i, x in enumerate(v, 1)) if field_name == "steps" else "\n".join(map(str, v))
    return "" if v is None else v


def _header(ws, row: int, names: list[str]) -> None:
    for c, n in enumerate(names, 1):
        cell = ws.cell(row, c, n)
        cell.fill, cell.font, cell.border = HEAD_FILL, HEAD_FONT, BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[row].height = 32


def _fill(cell, colours) -> None:
    bg, fg = colours
    cell.fill = PatternFill("solid", fgColor=bg)
    cell.font = Font(color=fg, bold=True)


def _safe_title(name: str) -> str:
    return re.sub(r"[\[\]:*?/\\]", "-", name)[:31]


def _id_in(req_id: str, text: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(req_id)}(?![\w-])", text, re.I) is not None


def _status(result: Optional[dict]) -> tuple[str, str, str, str]:
    """(status, actual, tested_by, comments) pre-filled from automated execution."""
    if not result:
        return "Not run", "", "", ""
    st = result.get("status")
    steps = result.get("steps_log") or []
    if st == "manual":
        return "Not run", "", "", (result.get("error") or "Could not be automated: run by hand.")[:800]
    if steps:                                     # web: say where it broke, not the whole page text
        bad = next((s for s in steps if s.get("status") == "failed"), None)
        final = (result.get("responses") or [{}])[-1]
        actual = (f"Step {bad.get('step') or 'final check'}: {bad.get('action')} "
                  f"'{bad.get('target') or bad.get('value')}' - {bad.get('detail')}" if bad else "All steps passed.")
        actual += f"\nPage: {final.get('url', '')}" if final.get("url") else ""
        shot = (bad or {}).get("screenshot") or next((s.get("screenshot") for s in reversed(steps) if s.get("screenshot")), "")
        status = {"passed": "Pass", "failed": "Fail", "error": "Blocked"}.get(st, "Not run")
        comment = (f"Automation could not perform a step: {result.get('error', '')[:300]} " if st == "error" else "")
        comment += f"Screenshot: {shot}" if shot else ""
        return status, actual[:1000], "Automation Engineer (agent)", comment.strip()
    actual = " / ".join((r.get("text") or "") for r in result.get("responses", []))[:1000]
    failed = "; ".join(f"{a['assertion']['type']}: {a['detail']}" for a in result.get("assertion_results", [])
                       if not a.get("passed"))
    status = {"passed": "Pass", "failed": "Fail", "flaky": "Fail", "error": "Blocked"}.get(st, "Not run")
    comment = {"flaky": "Flaky: passed and failed on repeated automated runs. ",
               "error": f"Automation error: {result.get('error', '')[:300]} "}.get(st, "")
    if failed:
        comment += f"Failed checks: {failed[:500]}"
    return status, actual, "Automation Engineer (agent)", comment.strip()


# ------------------------------------------------------------------ sheets
def _test_sheet(ws, run: RunData, skeleton: dict) -> None:
    cols = skeleton["columns"]
    names = [c["name"] for c in cols] + EXEC_COLS
    _header(ws, 1, names)
    pr_col = next((i for i, c in enumerate(cols, 1) if c["field"] == "priority"), None)
    st_col = len(cols) + 1
    tests = sorted(run.design.test_cases, key=lambda t: PRIORITY_ORDER.get(t.priority, 9))
    stamp = datetime.now().strftime("%Y-%m-%d")
    for r, tc in enumerate(tests, 2):
        d = tc.model_dump(mode="json")
        for c, col in enumerate(cols, 1):
            cell = ws.cell(r, c, _cell_value(d, col["field"]))
            cell.alignment, cell.border = WRAP, BORDER
        status, actual, by, comment = _status(run.results.get(tc.id))
        tri = run.triage.get(tc.id)
        if tri:
            verdict = {"product_bug": "product bug", "test_defect": "test defect (the check was wrong, not the system)",
                       "environment": "environment problem", "needs_review": "needs human review"}.get(
                tri["classification"], tri["classification"])
            comment = (f"Defect Manager: {verdict}. {tri.get('title', '')}"
                       + (f" Bug: {run.bugs[tc.id]}." if tc.id in run.bugs else "")
                       + (f" Recommendation: {tri['recommendation']}" if tri.get("recommendation") else "")
                       + (f"\n{comment}" if comment else ""))
        for c, v in enumerate([status, actual, by, stamp if by else "", comment], st_col):
            cell = ws.cell(r, c, v)
            cell.alignment, cell.border = WRAP, BORDER
            if c > st_col and not v:
                cell.fill = INPUT_FILL
        if pr_col:
            _fill(ws.cell(r, pr_col), PRIORITY_STYLE.get(tc.priority.value, ("FFFFFF", "000000")))
    last = len(tests) + 1
    if last >= 2:
        dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True,
                            showErrorMessage=True, errorTitle="Status", error="Pick a status from the list.")
        ws.add_data_validation(dv)
        letter = get_column_letter(st_col)
        dv.add(f"{letter}2:{letter}{max(last, 2) + 200}")          # room for manual additions
        for status, (bg, fg) in STATUS_STYLE.items():
            ws.conditional_formatting.add(f"{letter}2:{letter}{last + 200}", CellIsRule(
                operator="equal", formula=[f'"{status}"'], fill=PatternFill("solid", fgColor=bg),
                font=Font(color=fg, bold=True)))
    for c, col in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(c)].width = WIDTHS.get(col["field"], 18)
    for c, w in zip(range(st_col, st_col + 5), (12, 40, 18, 12, 36)):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(names))}{max(last, 1)}"


def _summary_sheet(ws, runs: list[RunData], title: str) -> None:
    ws["A1"] = title
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Generated by agentic-qa on {datetime.now():%d %b %Y, %H:%M}"
    ws["A2"].font = Font(italic=True, color="595959")
    head = ["Use case", "Name", "Test cases", "Critical", "High", "Medium", "Low", "End user", "Business", "Both",
            "Gaps for BA", "Requirements not covered", "Automated: pass", "Automated: fail"]
    _header(ws, 4, head)
    r = 5
    for run in runs:
        pr = Counter(t.priority.value for t in run.design.test_cases)
        pe = Counter(t.perspective.value for t in run.design.test_cases)
        traces = " ".join(" ".join(t.traceability) for t in run.design.test_cases)
        uncovered = sum(not _id_in(rid, traces) for rid, _, _ in run.requirements)
        res = Counter(v.get("status") for v in run.results.values())
        vals = [run.usecase_id, run.title, len(run.design.test_cases), pr["Critical"], pr["High"], pr["Medium"],
                pr["Low"], pe["End user"], pe["Business"], pe["Both"], len(run.design.gaps), uncovered,
                res["passed"] if run.results else "-", (res["failed"] + res["flaky"] + res["error"]) if run.results else "-"]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(r, c, v)
            cell.border, cell.alignment = BORDER, WRAP
        for c, p in zip(range(4, 8), ("Critical", "High", "Medium", "Low")):
            _fill(ws.cell(r, c), PRIORITY_STYLE[p])
        r += 1
    r += 1
    guide = [
        ("How to read this workbook", None),
        ("Test cases are sorted by priority: the first test is the most important. Run Critical and High first "
         "when time is short.", None),
        ("Priority = how bad it is if the test fails × how likely it is to happen.", None),
        ("Critical", "Data leak, money lost or wrongly taken, legal/compliance breach, or a core journey blocked."),
        ("High", "Wrong official information, or a common journey / important rule broken with no workaround."),
        ("Medium", "Less common path, a workaround exists, or confusing but not harmful."),
        ("Low", "Cosmetic, rare or minor inconvenience."),
        ("Perspective", "End user = what a real person experiences; Business = rules, money, compliance, operations."),
        ("Status column", "Pick Not run / Pass / Fail / Blocked / Not applicable. Pre-filled when tests ran automatically."),
        ("Light-yellow cells", "For you to fill in (actual result, tester, date, comments, BA answers)."),
        ("Gaps & Conflicts", "Questions for the BA. Tests listed there depend on the assumed answer until the BA replies."),
        ("Traceability (RTM)", "Which test cases cover each requirement; red rows are requirements with no test yet."),
    ]
    for label, text in guide:
        a = ws.cell(r, 1, label)
        if text is None:
            if label == "How to read this workbook":
                a.font = Font(bold=True, size=12, color="1F4E78")
            a.alignment = WRAP
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=10)
        else:
            a.font = Font(bold=True)
            if label in PRIORITY_STYLE:
                _fill(a, PRIORITY_STYLE[label])
            ws.cell(r, 2, text).alignment = WRAP
            ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=10)
        r += 1
    for c, w in enumerate([22, 46, 11, 9, 9, 9, 9, 10, 10, 9, 11, 14, 11, 11], 1):
        ws.column_dimensions[get_column_letter(c)].width = w


def _gaps_sheet(ws, runs: list[RunData]) -> None:
    head = ["Use case", "Gap ID", "Type", "What is unclear", "Impact on testing", "Question for BA",
            "Assumed for now", "Dependent test cases", "BA Answer", "Status"]
    _header(ws, 1, head)
    r = 2
    for run in runs:
        for g in run.design.gaps:
            deps = ", ".join(t.id for t in run.design.test_cases if t.based_on_assumption == g.id)
            vals = [run.usecase_id, g.id, g.type.value.replace("_", " "), g.description, g.impact, g.question_for_ba,
                    g.assumed_resolution, deps or "-", "", "Open"]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(r, c, v)
                cell.alignment, cell.border = WRAP, BORDER
            ws.cell(r, 9).fill = INPUT_FILL
            if g.type.value == "contradiction":
                _fill(ws.cell(r, 3), ("FFC7CE", "9C0006"))
            r += 1
    if r > 2:
        dv = DataValidation(type="list", formula1='"Open,Answered,Closed"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"J2:J{r + 100}")
    for c, w in enumerate([11, 9, 15, 48, 40, 44, 40, 22, 40, 11], 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:J{max(r - 1, 1)}"


def _rtm_sheet(ws, runs: list[RunData]) -> None:
    head = ["Use case", "Requirement ID", "Requirement", "Where it is written", "Covered by test cases",
            "Number of tests", "Highest priority", "Coverage"]
    _header(ws, 1, head)
    r = 2
    for run in runs:
        tests = run.design.test_cases
        known = set()
        rows = []
        for rid, text, src in run.requirements:
            known.add(rid.upper())
            cov = [t for t in tests if any(_id_in(rid, x) for x in t.traceability)]
            rows.append((rid, text, src, cov))
        # coverage labels used by tests that are not formal requirement IDs (e.g. "Intent: lookup a rule")
        extra = {}
        for t in tests:
            for x in t.traceability:
                if not any(_id_in(k, x) for k in known):
                    extra.setdefault(x, []).append(t)
        rows += [(lbl, "", "use-case analysis", ts) for lbl, ts in extra.items()]
        for rid, text, src, cov in rows:
            top = min((t.priority for t in cov), key=lambda p: PRIORITY_ORDER[p], default=None)
            vals = [run.usecase_id, rid, text[:400], src, ", ".join(t.id for t in cov), len(cov),
                    top.value if top else "-", "Covered" if cov else "NOT COVERED"]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(r, c, v)
                cell.alignment, cell.border = WRAP, BORDER
            if top:
                _fill(ws.cell(r, 7), PRIORITY_STYLE[top.value])
            _fill(ws.cell(r, 8), ("C6EFCE", "006100") if cov else ("FFC7CE", "9C0006"))
            r += 1
    for c, w in enumerate([11, 22, 60, 36, 34, 10, 12, 14], 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:H{max(r - 1, 1)}"


def _glossary_sheet(ws, runs: list[RunData], glossary: dict) -> None:
    _header(ws, 1, ["Abbreviation", "Meaning"])
    text = " ".join(json.dumps(t.model_dump(mode="json")) for run in runs for t in run.design.test_cases)
    used = {k: v for k, v in glossary.items() if re.search(rf"(?<![A-Za-z]){re.escape(k)}(?![A-Za-z])", text)}
    for r, (k, v) in enumerate(sorted((used or glossary).items()), 2):
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, v)
        for c in (1, 2):
            ws.cell(r, c).border = BORDER
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 70


# ------------------------------------------------------------------ public
def _load_config(skeleton_path, glossary_path):
    skeleton = yaml.safe_load(Path(skeleton_path).read_text(encoding="utf-8"))
    g = Path(glossary_path)
    glossary = (yaml.safe_load(g.read_text(encoding="utf-8")) or {}).get("terms", {}) if g.exists() else {}
    return skeleton, glossary


def build_workbook(runs: list[RunData], out_path: Path, title: str, skeleton_path="config/testcase_skeleton.yaml",
                   glossary_path="config/glossary.yaml") -> Path:
    skeleton, glossary = _load_config(skeleton_path, glossary_path)
    wb = Workbook()
    _summary_sheet(wb.active, runs, title)
    wb.active.title = "Summary"
    for run in runs:
        name = "Test Cases" if len(runs) == 1 else _safe_title(f"TC {run.usecase_id}")
        _test_sheet(wb.create_sheet(name), run, skeleton)
    _gaps_sheet(wb.create_sheet("Gaps & Conflicts"), runs)
    _rtm_sheet(wb.create_sheet("Traceability (RTM)"), runs)
    _glossary_sheet(wb.create_sheet("Glossary"), runs, glossary)
    for ws in wb.worksheets:                                   # printable: landscape, fit to page width
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        if ws.title.startswith(("TC ", "Test Cases")):        # wide: print at readable size across pages
            ws.print_title_rows, ws.print_title_cols = "1:1", "A:A"
        else:
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
            if ws.title != "Summary":
                ws.print_title_rows = "1:1"
    wb.active = 1 if len(wb.sheetnames) > 1 else 0          # open on the (first) test-case sheet
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    return out_path


def export_run(run_dir: Path, **kw) -> Path:
    run = load_run(run_dir)
    return build_workbook([run], Path(run_dir) / "02_testcases.xlsx", f"Test cases: {run.usecase_id} {run.title}", **kw)


def export_batch(batch_dir: Path, **kw) -> Optional[Path]:
    batch_dir = Path(batch_dir)
    runs = [load_run(d) for d in sorted(batch_dir.glob("SCN-*")) if (d / "02_testcases.json").exists()]
    if not runs:
        return None
    return build_workbook(runs, batch_dir / f"test_cases_{batch_dir.name}.xlsx",
                          f"Test cases: {len(runs)} use case(s)", **kw)
