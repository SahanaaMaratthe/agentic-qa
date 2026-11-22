"""Builders for synthetic requirement documents with deliberately different layouts.

Each one represents a structure that real clients use and that the VTU samples don't show.
Run `python tests/synthetic.py out_dir/` to write them all out for manual inspection.
"""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl


def usecase_catalogue_xlsx(path: Path) -> Path:
    """One row per use case, header on row 3, multi-row records, merged cells, cover/history/hidden sheets."""
    wb = openpyxl.Workbook()
    cover = wb.active
    cover.title = "Cover"
    cover["A1"] = "ACME Retail — Requirements Pack v3"
    hist = wb.create_sheet("Revision History")
    hist.append(["Version", "Date", "Author"])
    hist.append(["0.1", "2026-01-10", "BA team"])
    hidden = wb.create_sheet("Lookups")
    hidden.append(["Actor"])
    hidden.append(["Customer"])
    hidden.sheet_state = "hidden"
    ws = wb.create_sheet("Use Cases")
    ws["A1"] = "ACME Retail — Use Case Catalogue"
    ws.merge_cells("A1:E1")
    ws.append([])
    ws.append(["Ref", "Use Case Name", "Actor", "Main Flow", "Acceptance Criteria"])          # row 3
    ws.append(["UC-01", "Login with OTP", "Customer", "1. Enter mobile number", "OTP valid for 5 minutes"])
    ws.append([None, None, None, "2. Enter the OTP received by SMS", "Account locked after 3 wrong attempts"])
    ws.append(["UC-02", "Reset password", "Customer", "Request reset link by email", "Link expires after 24 hours"])
    ws.append(["UC-03", "Checkout", "Customer", "1. Review cart", "Cart total includes tax"])          # row 7
    ws.append([None, None, None, "2. Pay by card or UPI", "Payment confirmation within 10 seconds"])  # row 8
    ws.merge_cells("A7:A8")
    ws.merge_cells("B7:B8")
    ws.merge_cells("C7:C8")
    wb.save(path)
    return path


def no_structure_xlsx(path: Path) -> Path:
    """A handful of requirements with no IDs and no scenarios."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Requirements"
    ws.append(["Requirement", "Details"])
    for i in range(5):
        ws.append([f"Requirement about topic {i}", f"Details for topic {i}"])
    wb.save(path)
    return path


def many_ids_no_scenarios_xlsx(path: Path) -> Path:
    """20 ID'd requirements but nothing that says how they group into use cases."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reqs"
    ws.append(["Req ID", "Description"])
    for i in range(1, 21):
        ws.append([f"REQ-{i:03d}", f"The system shall do thing number {i}."])
    wb.save(path)
    return path


def custom_ids_docx(path: Path) -> Path:
    """Word BRD: features as headings, a client-specific ID style 'SR/1001', a table with a vertical merge."""
    import docx

    d = docx.Document()
    d.add_heading("ACME Loyalty — Business Requirements", 0)
    d.add_paragraph("Document ID: ACME-BRD-2026-07")
    d.add_heading("1. Introduction", 1)
    d.add_paragraph("This document describes two features of the loyalty programme.")
    d.add_heading("2. Feature 1: Store locator", 1)
    d.add_paragraph("SR/1001 The app shall show the 10 nearest stores.", style="List Number")
    d.add_paragraph("SR/1002 Store hours shall be shown in local time.", style="List Number")
    d.add_heading("3. Feature 2: Loyalty points", 1)
    t = d.add_table(rows=4, cols=3)
    for c, h in zip(t.rows[0].cells, ["Requirement", "Description", "Priority"]):
        c.text = h
    rows = [("SR/2001", "Earn 1 point per 100 INR spent", "High"),
            ("SR/2002", "Points expire after 12 months", "High"),
            ("", "Expiry warning sent 30 days before", "")]
    for r, vals in zip(t.rows[1:], rows):
        for c, v in zip(r.cells, vals):
            c.text = v
    t.cell(2, 2).merge(t.cell(3, 2))      # vertical merge in the Priority column
    d.save(path)
    return path


def split_table_pdf(path: Path) -> Path:
    """A table that continues onto page 2 WITHOUT a repeated header, plus a running footer."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(50, 30, f"ACME Payments Spec | Confidential | Page {doc.page} of 2")

    story = [Paragraph("ACME Payments — Functional Specification", ss["Title"]),
             Paragraph("1. Module A: Card Payments", ss["Heading1"]),
             Paragraph("The following requirements apply to card payments.", ss["BodyText"]),
             Spacer(1, 340)]
    data = [["Req ID", "Requirement"]] + [[f"PAY-{i:02d}", f"Card payment rule number {i} must be enforced."]
                                          for i in range(1, 31)]
    t = Table(data, colWidths=[80, 380], repeatRows=0)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                           ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]))
    story.append(t)
    SimpleDocTemplate(str(path), pagesize=A4).build(story, onFirstPage=footer, onLaterPages=footer)
    return path


ALL = {
    "usecase_catalogue.xlsx": usecase_catalogue_xlsx,
    "no_structure.xlsx": no_structure_xlsx,
    "many_ids_no_scenarios.xlsx": many_ids_no_scenarios_xlsx,
    "custom_ids.docx": custom_ids_docx,
    "split_table.pdf": split_table_pdf,
}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "synthetic_samples")
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in ALL.items():
        print(fn(out / name))
