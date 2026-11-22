"""Common document model shared by every ingest plug-in.

Every reader turns its format into an `IngestedDocument` (a flat list of
`Block`s). Everything after reading works on this model only, so a new file
format never requires changes to cleaning, segmenting, matching or conflict
detection.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """Where a piece of content came from: printed in gaps and use cases for traceability."""

    file: str
    sheet: Optional[str] = None
    page: Optional[int] = None
    row: Optional[int] = None          # 1-based spreadsheet row, or table row index
    section: Optional[str] = None

    def label(self) -> str:
        parts = [self.file]
        if self.sheet:
            parts.append(f"sheet '{self.sheet}'")
        if self.page:
            parts.append(f"page {self.page}")
        if self.row:
            parts.append(f"row {self.row}")
        return ", ".join(parts)


class TableRow(BaseModel):
    cells: dict[str, str]              # header -> value (empty values omitted)
    ref: SourceRef


class Block(BaseModel):
    kind: str                          # heading | paragraph | list_item | table
    text: str = ""
    level: int = 0                     # heading level (1 = top)
    headers: list[str] = []            # table only
    rows: list[TableRow] = []          # table only
    ref: SourceRef
    meta: dict[str, Any] = {}


class IngestedDocument(BaseModel):
    name: str                          # display name (file name)
    path: str
    format: str                        # xlsx | pdf | docx | text
    title: str = ""
    role: str = "document"             # brd | brs | document  (detected)
    doc_ids: list[str] = []            # e.g. VTU-BRD-2026-01
    parent_ids: list[str] = []         # documents this one traces to
    blocks: list[Block] = []
    warnings: list[str] = []


class Item(BaseModel):
    """One requirement-ish unit: a table row, a list item or a paragraph."""

    uid: str                           # unique inside the run
    item_id: Optional[str] = None      # business ID if present (BO-01, FR-GRV-03 ...)
    doc: str                           # document name
    role: str
    section: str = ""                  # sheet / heading path
    fields: dict[str, str] = {}        # table rows
    text: str = ""                     # prose items
    ref: SourceRef
    scenario_hint: Optional[str] = None   # explicit label on the item itself (scenario column value / leading mention)
    has_scenario_column: bool = False     # the item's table has a scenario column (empty/other value = shared)
    heading_hint: Optional[str] = None    # nearest enclosing heading that names a scenario
    front_matter: bool = False            # cover / document-control content before the first section
    scenarios: list[str] = []          # assigned scenario keys
    assigned_by: str = ""              # explicit | heading | keyword | shared
    traces: list[str] = []             # IDs this item says it traces to

    def content(self, exclude: tuple[str, ...] = ()) -> str:
        if self.fields:
            return " | ".join(f"{k}: {v}" for k, v in self.fields.items() if k not in exclude)
        return self.text


class Scenario(BaseModel):
    key: str                           # SCN-01 ...
    name: str
    aliases: list[str] = []
    ordinal: Optional[int] = None
    keywords: list[str] = []
    found_in: list[str] = []           # documents that mention it


class Conflict(BaseModel):
    id: str
    kind: str                          # same_id_different_text | version_mismatch | similar_item_different_numbers
    description: str
    question: str
    sources: list[str]
    scenarios: list[str] = []
    confidence: str = "high"           # high | medium


class ScenarioPackage(BaseModel):
    scenario: Scenario
    items: list[Item]
    conflicts: list[Conflict] = []
    text: str = ""                     # rendered use-case text handed to the Requirement Analyst


class IngestReport(BaseModel):
    documents: list[dict] = []
    scenarios: list[dict] = []
    conflicts: list[Conflict] = []
    warnings: list[str] = []
    confidence: str = "high"           # high | medium | low
    confidence_reasons: list[str] = []
    ok_to_continue: bool = True


class IngestResult(BaseModel):
    documents: list[IngestedDocument]
    scenarios: list[Scenario]
    items: list[Item]
    packages: list[ScenarioPackage]
    report: IngestReport
    extra: dict[str, Any] = Field(default_factory=dict)
