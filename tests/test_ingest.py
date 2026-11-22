"""Regression tests for reading documents.

* the four VTU samples (real structure, provided by the QA team) with expected results
* synthetic layouts the samples don't cover (tests/synthetic.py)
* drive sources against simulated Google Drive / Microsoft Graph APIs
* the plug-in mechanism (a developer adds a reader without touching existing code)
"""
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

from qa_agents.ingest import registry  # noqa: E402
from qa_agents.ingest.model import IngestedDocument, Block, SourceRef  # noqa: E402
from qa_agents.ingest.pipeline import IngestPipeline  # noqa: E402
from qa_agents.ingest.profile import load_profile  # noqa: E402
from qa_agents.ingest.readers import Reader  # noqa: E402
from qa_agents.ingest.sources.gdrive import GoogleDriveSource, parse_drive_id  # noqa: E402
from qa_agents.ingest.sources.sharepoint import SharePointSource, share_id  # noqa: E402
from tests import synthetic  # noqa: E402

S = ROOT / "tests" / "fixtures" / "samples"
BRD_X, BRS_X, BRD_P, BRS_P = (str(S / n) for n in ("VTU_BRD.xlsx", "VTU_BRS.xlsx", "VTU_BRD.pdf", "VTU_BRS.pdf"))


def run(inputs, tmp_path, profile=None):
    return IngestPipeline(profile=profile, log=lambda *_: None).run([str(i) for i in inputs], tmp_path)


def by_id(res, iid, doc_part):
    return next(it for it in res.items if it.item_id == iid and doc_part in it.doc)


# ------------------------------------------------------------------ VTU samples
@pytest.fixture(scope="module")
def all4(tmp_path_factory):
    return run([BRD_X, BRS_X, BRD_P, BRS_P], tmp_path_factory.mktemp("all4"))


def test_samples_two_scenarios_matched_across_all_four_files(all4):
    assert [s.key for s in all4.scenarios] == ["SCN-01", "SCN-02"]
    assert "eDDTS" in all4.scenarios[0].name
    assert "Grievance" in all4.scenarios[1].name
    assert all(len(s.found_in) == 4 for s in all4.scenarios)
    assert all4.report.confidence == "high"


def test_samples_document_roles_and_traceability(all4):
    docs = {d.name: d for d in all4.documents}
    assert docs["VTU_BRS.xlsx"].role == "brs" and docs["VTU_BRD.pdf"].role == "brd"
    assert docs["VTU_BRS.pdf"].doc_ids == ["VTU-BRS-2026-01"]
    assert docs["VTU_BRS.pdf"].parent_ids == ["VTU-BRD-2026-01"]
    assert by_id(all4, "FR-EDD-04", "VTU_BRS.xlsx").traces == ["BO-02", "BR-EDD-03"]


@pytest.mark.parametrize("iid,doc,expected", [
    ("BO-01", "VTU_BRD.xlsx", ["SCN-01"]),          # explicit scenario column
    ("BR-GRV-02", "VTU_BRD.xlsx", ["SCN-02"]),
    ("BO-06", "VTU_BRD.xlsx", ["SHARED"]),          # "Shared / Cross-Portal"
    ("FR-EDD-07", "VTU_BRS.pdf", ["SCN-01"]),       # under heading "Module A: eDDTS Portal"
    ("FR-GRV-03", "VTU_BRS.pdf", ["SCN-02"]),       # under heading "Module B: ..."
    ("BR-eDDTS-01", "VTU_BRD.pdf", ["SCN-01"]),     # ID in brackets inside a paragraph
    ("BR-04", "VTU_BRD.pdf", ["SCN-02"]),           # no label: keyword "grievances"
    ("NFR-03", "VTU_BRS.xlsx", ["SHARED"]),
])
def test_samples_item_assignment(all4, iid, doc, expected):
    assert by_id(all4, iid, doc).scenarios == expected


def test_samples_state_machine_sheet_goes_to_eddts_by_its_title(all4):
    rows = [it for it in all4.items if it.doc == "VTU_BRS.xlsx" and "State_Transitions" in it.section]
    assert len(rows) == 7 and all(it.scenarios == ["SCN-01"] for it in rows)


def test_samples_conflicts_found(all4):
    text = " ".join(c.description for c in all4.report.conflicts)
    kinds = {c.kind for c in all4.report.conflicts}
    assert {"same_id_different_content", "document_version_mismatch",
            "similar_item_different_numbers", "field_length_mismatch"} <= kinds
    assert "BO-01 is defined differently" in text
    assert "99.9% vs 99.5%" in text or "99.5% vs 99.9%" in text
    assert "VARCHAR 12" in text and "VARCHAR 10" in text


def test_samples_uncalculated_formulas_dropped_with_warning(all4):
    assert any("formula cell" in w for w in all4.report.warnings)
    assert not any("COUNTIF" in (it.content() or "") for it in all4.items)


def test_samples_pdf_page_footers_removed(all4):
    assert not any("Page 1 of" in (it.content() or it.text) for it in all4.items)


def test_samples_package_text_traceable(all4, tmp_path):
    pkg = all4.packages[0]
    assert pkg.text.startswith("# SCN-01:")
    assert "_(source: VTU_BRS.xlsx, sheet '2_Functional_Requirements', row 6)_" in pkg.text
    assert "Conflicts detected automatically" in pkg.text


def test_samples_single_pdf_alone(tmp_path):
    res = run([BRD_P], tmp_path)
    assert len(res.scenarios) == 2 and res.report.conflicts == []


def test_saved_intermediate_outputs(all4, tmp_path):
    res = run([BRS_X], tmp_path)
    out = tmp_path / "00_ingest"
    for f in ("documents.json", "items.json", "report.json", "report.md", "SCN-01.md"):
        assert (out / f).exists(), f
    assert json.loads((out / "report.json").read_text())["confidence"] == "high"


# ------------------------------------------------------------------ synthetic layouts
def test_usecase_catalogue_rows_multirow_merged_and_skipped_sheets(tmp_path):
    f = synthetic.usecase_catalogue_xlsx(tmp_path / "cat.xlsx")
    res = run([f], tmp_path / "out")
    assert [s.name for s in res.scenarios] == ["Login with OTP", "Reset password", "Checkout"]
    uc1 = by_id(res, "UC-01", "cat.xlsx")
    assert "Enter the OTP" in uc1.fields["Main Flow"] and "3 wrong attempts" in uc1.fields["Acceptance Criteria"]
    uc3 = by_id(res, "UC-03", "cat.xlsx")
    assert "Pay by card" in uc3.fields["Main Flow"]
    w = " ".join(res.report.warnings)
    assert "'Cover'" in w and "'Revision History'" in w and "'Lookups' (hidden)" in w


def test_no_structure_is_one_usecase_medium(tmp_path):
    res = run([synthetic.no_structure_xlsx(tmp_path / "n.xlsx")], tmp_path / "o")
    assert res.report.confidence == "medium" and len(res.packages) == 1 and res.report.ok_to_continue


def test_many_ids_without_grouping_stops_with_low_confidence(tmp_path):
    res = run([synthetic.many_ids_no_scenarios_xlsx(tmp_path / "m.xlsx")], tmp_path / "o")
    assert res.report.confidence == "low" and not res.report.ok_to_continue


def test_docx_features_and_client_specific_ids_via_profile(tmp_path):
    f = synthetic.custom_ids_docx(tmp_path / "c.docx")
    plain = run([f], tmp_path / "o1")
    assert [s.name for s in plain.scenarios] == ["Store locator", "Loyalty points"]
    assert not any(it.item_id and it.item_id.startswith("SR/") for it in plain.items)
    client = run([f], tmp_path / "o2", profile="example_client")
    ids = {it.item_id for it in client.items if it.item_id}
    assert {"SR/1001", "SR/2001", "SR/2002"} <= ids
    sr2002 = by_id(client, "SR/2002", "c.docx")
    assert "Expiry warning" in sr2002.fields["Description"]          # multi-row record grouped
    assert by_id(client, "SR/1001", "c.docx").scenarios == ["SCN-01"]


def test_pdf_table_split_across_pages_without_repeated_header(tmp_path):
    res = run([synthetic.split_table_pdf(tmp_path / "p.pdf")], tmp_path / "o")
    ids = [it.item_id for it in res.items if it.item_id]
    assert ids == [f"PAY-{i:02d}" for i in range(1, 31)]
    assert not any("Confidential" in (it.content() or it.text) for it in res.items)
    assert res.scenarios[0].name == "Card Payments"


def test_legacy_and_unsupported_formats_reported(tmp_path):
    (tmp_path / "old.xls").write_bytes(b"x")
    (tmp_path / "a.md").write_text("# UC-9: Tiny\n\nUsers can log in.\n")
    res = run([tmp_path / "old.xls", tmp_path / "a.md"], tmp_path / "o")
    assert any("Save As" in w for w in res.report.warnings)


def test_profile_inheritance():
    p = load_profile("example_client")
    base = load_profile("default")
    assert len(p.id_patterns) == len(base.id_patterns) + 1
    assert p.sheet_override("Use Cases").header_row == 3
    assert p.cleaners == base.cleaners


# ------------------------------------------------------------------ drive sources (simulated APIs)
class FakeResp:
    def __init__(self, status=200, json_data=None, content=b""):
        self.status_code, self._json, self.content, self.text = status, json_data, content, ""

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, **kw):
        self.calls.append((url, params))
        for key, resp in self.routes:
            if key(url, params or {}):
                return resp
        return FakeResp(404)


@pytest.mark.parametrize("url,expected", [
    ("https://drive.google.com/file/d/1AbCdEfGhIjKlMn/view?usp=sharing", "1AbCdEfGhIjKlMn"),
    ("https://drive.google.com/drive/u/0/folders/0BxYzFolderId123", "0BxYzFolderId123"),
    ("https://drive.google.com/open?id=1AbCdEfGhIjKlMn", "1AbCdEfGhIjKlMn"),
    ("https://docs.google.com/spreadsheets/d/1SheetIdABCDEFG/edit#gid=0", "1SheetIdABCDEFG"),
    ("gdrive://1AbCdEfGhIjKlMn", "1AbCdEfGhIjKlMn"),
    ("https://example.com/file.pdf", None),
])
def test_gdrive_link_parsing(url, expected):
    assert parse_drive_id(url) == expected


def test_gdrive_folder_fetch_exports_google_sheets_and_skips_unsupported(tmp_path):
    xlsx = synthetic.no_structure_xlsx(tmp_path / "x.xlsx").read_bytes()
    pdf = Path(BRD_P).read_bytes()
    api = "https://www.googleapis.com/drive/v3/files"
    routes = [
        (lambda u, p: u == f"{api}/1FolderAbcDEF123", FakeResp(json_data={"id": "1FolderAbcDEF123", "name": "BRDs",
                                                               "mimeType": "application/vnd.google-apps.folder"})),
        (lambda u, p: u == api and "'1FolderAbcDEF123' in parents" in p.get("q", ""), FakeResp(json_data={"files": [
            {"id": "S1", "name": "Use cases", "mimeType": "application/vnd.google-apps.spreadsheet"},
            {"id": "P1", "name": "BRD.pdf", "mimeType": "application/pdf"},
            {"id": "I1", "name": "logo.png", "mimeType": "image/png"}]})),
        (lambda u, p: u == f"{api}/S1/export", FakeResp(content=xlsx)),
        (lambda u, p: u == f"{api}/P1" and p.get("alt") == "media", FakeResp(content=pdf)),
    ]
    src = GoogleDriveSource({}, session=FakeSession(routes))
    got = src.fetch("https://drive.google.com/drive/folders/1FolderAbcDEF123", tmp_path / "dl")
    assert [n for _, n in got] == ["Drive: BRDs/BRD.pdf", "Drive: BRDs/Use cases.xlsx"]
    assert all(p.exists() and p.stat().st_size > 0 for p, _ in got)


def test_gdrive_access_denied_message(tmp_path):
    src = GoogleDriveSource({}, session=FakeSession([(lambda u, p: True, FakeResp(403))]))
    with pytest.raises(RuntimeError, match="access denied"):
        src.fetch("gdrive://1AbCdEfGhIjKlMn", tmp_path)


def test_sharepoint_share_id_and_folder_fetch(tmp_path):
    url = "https://contoso.sharepoint.com/:f:/s/QA/EaBcDeF"
    sid = share_id(url)
    assert sid.startswith("u!") and "=" not in sid and "/" not in sid
    g = "https://graph.microsoft.com/v1.0"
    docx_bytes = synthetic.custom_ids_docx(tmp_path / "c.docx").read_bytes()
    routes = [
        (lambda u, p: u.startswith(f"{g}/shares/{sid}/driveItem"),
         FakeResp(json_data={"id": "F", "name": "Specs", "folder": {}, "parentReference": {"driveId": "D"}})),
        (lambda u, p: u.startswith(f"{g}/drives/D/items/F/children"), FakeResp(json_data={"value": [
            {"id": "A", "name": "Loyalty BRD.docx", "file": {}, "parentReference": {"driveId": "D"}},
            {"id": "B", "name": "notes.zip", "file": {}, "parentReference": {"driveId": "D"}}]})),
        (lambda u, p: u == f"{g}/drives/D/items/A/content", FakeResp(content=docx_bytes)),
    ]
    src = SharePointSource({}, session=FakeSession(routes))
    assert src.can_handle(url) and src.can_handle("sharepoint://contoso.sharepoint.com/sites/QA/Docs")
    assert not src.can_handle("https://drive.google.com/file/d/1AbCdEfGhIjKlMn")
    got = src.fetch(url, tmp_path / "dl")
    assert [n for _, n in got] == ["SharePoint: Specs/Loyalty BRD.docx"]


def test_local_folder_source_picks_supported_files(tmp_path):
    synthetic.no_structure_xlsx(tmp_path / "a.xlsx")
    (tmp_path / "~$a.xlsx").write_bytes(b"lock file")
    (tmp_path / "image.png").write_bytes(b"png")
    files = IngestPipeline(log=lambda *_: None).fetch([str(tmp_path)], tmp_path / "dl")
    assert [n for _, n in files] == ["a.xlsx"]


# ------------------------------------------------------------------ plug-ins
def test_developer_can_add_a_reader_plugin(tmp_path):
    @registry.register("reader", "csv_demo")
    class CsvReader(Reader):
        extensions = (".csv",)

        def read(self, path, profile, display_name=None):
            import csv
            from qa_agents.ingest.tables import table_from_rows
            rows = list(csv.reader(path.open()))
            refs = [SourceRef(file=path.name, row=i + 1) for i in range(len(rows))]
            headers, trows = table_from_rows(rows, refs)
            return IngestedDocument(name=path.name, path=str(path), format="csv",
                                    blocks=[Block(kind="table", headers=headers, rows=trows, ref=refs[0])])

    f = tmp_path / "reqs.csv"
    f.write_text("ID,Scenario,Requirement\nR-01,Scenario 1: Ordering,Customer can order\n"
                 "R-02,Scenario 2: Returns,Customer can return\n")
    try:
        res = run([f], tmp_path / "o")
        assert [s.name for s in res.scenarios] == ["Ordering", "Returns"]
        assert by_id(res, "R-02", "reqs.csv").scenarios == ["SCN-02"]
    finally:
        registry._REGISTRY["reader"].pop("csv_demo", None)


def test_unknown_plugin_name_gives_helpful_error():
    with pytest.raises(KeyError, match="Available"):
        registry.get("cleaner", "does_not_exist")
