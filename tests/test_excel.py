"""Excel workbooks: sheets, ordering, colours, dropdowns, automated status, triage, traceability."""
import json
import os
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

from qa_agents import service  # noqa: E402
from qa_agents.__main__ import main  # noqa: E402
from qa_agents.orchestrator import Pipeline, load_usecase  # noqa: E402

SAMPLES = str(ROOT / "tests" / "fixtures" / "samples")


@pytest.fixture(scope="module")
def uc_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("uc")
    Pipeline("config/settings.yaml", log=lambda *_: None).run(d, load_usecase(Path("inputs/usecases/UC-001_rules_agent.md")))
    return d


@pytest.fixture(scope="module")
def batch(tmp_path_factory):
    d = tmp_path_factory.mktemp("batch")
    pv = service.preview([SAMPLES], batch_dir=d, log=lambda *_: None)
    out = service.run_batch(pv, until="design", log=lambda *_: None)
    return d, out


def headers(ws):
    return [c.value for c in ws[1]]


def test_workbook_sheets_and_columns(uc_run):
    wb = openpyxl.load_workbook(uc_run / "02_testcases.xlsx")
    assert wb.sheetnames == ["Summary", "Test Cases", "Gaps & Conflicts", "Traceability (RTM)", "Glossary"]
    h = headers(wb["Test Cases"])
    for col in ("Test Case ID", "Priority", "Why this Priority", "Perspective", "Purpose", "Business Impact",
                "Status", "Actual Result", "Tested By", "Test Date", "Comments"):
        assert col in h
    assert wb.active.title == "Test Cases"                       # opens on the test cases
    assert wb["Test Cases"].freeze_panes == "B2" and wb["Test Cases"].auto_filter.ref


def test_sorted_by_priority_with_colours(uc_run):
    ws = openpyxl.load_workbook(uc_run / "02_testcases.xlsx")["Test Cases"]
    pi = headers(ws).index("Priority") + 1
    pr = [ws.cell(r, pi).value for r in range(2, ws.max_row + 1)]
    assert pr == sorted(pr, key=["Critical", "High", "Medium", "Low"].index)
    assert ws.cell(2, pi).fill.fgColor.rgb.endswith("FFC7CE")    # Critical = light red


def test_status_prefilled_from_automation_with_triage_and_dropdown(uc_run):
    ws = openpyxl.load_workbook(uc_run / "02_testcases.xlsx")["Test Cases"]
    h = headers(ws)
    rows = {ws.cell(r, 1).value: {k: ws.cell(r, i + 1).value for i, k in enumerate(h)} for r in range(2, ws.max_row + 1)}
    assert [k for k, v in rows.items() if v["Status"] == "Fail"] == ["TC-UC-001-001", "TC-UC-001-005", "TC-UC-001-006"]
    assert "product bug" in rows["TC-UC-001-001"]["Comments"] and "BUG-UC-001-" in rows["TC-UC-001-001"]["Comments"]
    assert "test defect" in rows["TC-UC-001-005"]["Comments"]
    assert rows["TC-UC-001-002"]["Tested By"] == "Automation Engineer (agent)"
    dv = ws.data_validations.dataValidation
    assert any('"Not run,Pass,Fail,Blocked,Not applicable"' == v.formula1 for v in dv)


def test_gaps_sheet_has_ba_columns(uc_run):
    ws = openpyxl.load_workbook(uc_run / "02_testcases.xlsx")["Gaps & Conflicts"]
    h = headers(ws)
    assert h[-2:] == ["BA Answer", "Status"] and ws.max_row > 1
    assert ws.cell(2, h.index("Status") + 1).value == "Open"


def test_summary_counts(uc_run):
    ws = openpyxl.load_workbook(uc_run / "02_testcases.xlsx")["Summary"]
    row = [c.value for c in ws[5]]
    assert row[0] == "UC-001" and row[2] == 12 and row[3:7] == [2, 6, 3, 1]
    assert row[12] == 9                                          # automated passes


def test_batch_workbook_one_sheet_per_usecase_and_rtm(batch):
    d, out = batch
    assert out.workbook and out.workbook.exists()
    wb = openpyxl.load_workbook(out.workbook)
    assert wb.sheetnames == ["Summary", "TC SCN-01", "TC SCN-02", "Gaps & Conflicts", "Traceability (RTM)", "Glossary"]
    rtm = wb["Traceability (RTM)"]
    h = headers(rtm)
    rows = [{k: rtm.cell(r, i + 1).value for i, k in enumerate(h)} for r in range(2, rtm.max_row + 1)]
    fr = next(r for r in rows if r["Requirement ID"] == "FR-EDD-04")
    assert fr["Use case"] == "SCN-01" and "VTU_BRS" in fr["Where it is written"]
    assert fr["Coverage"] == "NOT COVERED"                       # mock tests don't trace to VTU IDs
    gaps = wb["Gaps & Conflicts"]
    assert any(gaps.cell(r, 2).value.startswith("CF-") for r in range(2, gaps.max_row + 1))
    assert (d / "SCN-01" / "02_testcases.xlsx").exists()


def test_rtm_marks_covered_requirements(batch, tmp_path):
    d, _ = batch
    tc_file = d / "SCN-01" / "02_testcases.json"
    data = json.loads(tc_file.read_text())
    data["test_cases"][0]["traceability"] = ["FR-EDD-04"]
    tc_file.write_text(json.dumps(data))
    assert main(["export", "--run-dir", str(d)]) == 0             # rebuild after a manual edit
    rtm = openpyxl.load_workbook(next(d.glob("test_cases_*.xlsx")))["Traceability (RTM)"]
    h = headers(rtm)
    row = next(r for r in range(2, rtm.max_row + 1) if rtm.cell(r, 2).value == "FR-EDD-04")
    assert rtm.cell(row, h.index("Coverage") + 1).value == "Covered"
    assert rtm.cell(row, h.index("Covered by test cases") + 1).value == data["test_cases"][0]["id"]
