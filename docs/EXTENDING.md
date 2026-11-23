# Extending agentic-qa

This guide is for developers who want to improve or adapt the tool. The rule of thumb:
**add a plug-in or a profile setting; don't edit existing, tested code** unless you are fixing a bug.

## 1. Architecture

```
inputs (files, folders, Drive / SharePoint links)
  │
  ▼  INGEST  (qa_agents/ingest/)                        nothing here calls an AI model
  fetch ─► read ─► annotate ─► clean ─► extract items ─► find scenarios ─► match across documents
        source    reader       BRD/BRS,  cleaner(s)                     scenario_finder(s)
        plug-ins  plug-ins     doc IDs   plug-ins
                                                   ─► assign items ─► detect conflicts ─► assemble packages
                                                      assigner        conflict_detector(s)   one per scenario
  │
  ▼  AGENTS  (qa_agents/agents/, prompts in qa_agents/prompts/)
  Requirement Analyst ─► Test Designer ─► Automation Engineer ─► Defect Manager
                         (+ conflicts added as gaps)
```

* `qa_agents/service.py` is the public API (`preview`, `run_batch`). The CLI (`__main__.py`) and the
  web page (`ui/app.py`) both call it; call it from your own integrations too.
* Every ingest stage writes its output to `<batch>/00_ingest/` (`documents.json`, `items.json`,
  `report.md`, `SCN-xx.md`). When a split looks wrong, start there.
* Data contracts: `qa_agents/ingest/model.py` (documents, blocks, items, scenarios, conflicts) and
  `qa_agents/core/models.py` (use cases, test cases, gaps, results, bugs).

## 2. Plug-in kinds

| Kind | Base class | Contract | Built-ins |
|---|---|---|---|
| `source` | `ingest.sources.Source` | `can_handle(uri)`, `fetch(uri, dest) -> [(path, display_name)]`, `priority` | local, gdrive, sharepoint |
| `reader` | `ingest.readers.Reader` | `extensions`, `read(path, profile, display_name) -> IngestedDocument` | xlsx, pdf, docx, text |
| `cleaner` | `ingest.cleaners.Cleaner` | `apply(doc, profile) -> doc` | skip_sheets, drop_page_furniture, merge_split_tables, group_multirow_records, drop_empty |
| `scenario_finder` | `ingest.scenarios.ScenarioFinder` | `find(doc, profile) -> [Mention]` | scenario_column, scenario_heading, scenario_definition_row |
| `assigner` | `ingest.scenarios.Assigner` | `assign(items, scenarios, mapping, profile)` (sets `item.scenarios`) | explicit_then_keyword |
| `conflict_detector` | `ingest.conflicts.ConflictDetector` | `detect(items, docs, profile) -> [Conflict]` | same_id_different_content, document_version_mismatch, similar_item_different_numbers, field_length_mismatch |

Cleaners, finders, the assigner and conflict detectors run **in the order listed in the client
profile**, so a new one is switched on by adding its name to the profile, per client if needed.

## 3. Adding a plug-in (worked example: a CSV reader)

```python
# my_company/qa_plugins/csv_reader.py
import csv
from qa_agents.ingest.registry import register
from qa_agents.ingest.readers import Reader
from qa_agents.ingest.model import Block, IngestedDocument, SourceRef
from qa_agents.ingest.tables import table_from_rows

@register("reader", "csv")
class CsvReader(Reader):
    extensions = (".csv",)

    def read(self, path, profile, display_name=None):
        rows = list(csv.reader(path.open(encoding="utf-8-sig")))
        refs = [SourceRef(file=path.name, row=i + 1) for i in range(len(rows))]
        headers, trows = table_from_rows(rows, refs)
        return IngestedDocument(name=display_name or path.name, path=str(path), format="csv",
                                blocks=[Block(kind="table", headers=headers, rows=trows, ref=refs[0])])
```

Load it one of two ways:

1. **settings.yaml**: `ingest: {plugins: [my_company.qa_plugins.csv_reader]}`
2. **Python entry point** (when you ship plug-ins as a package):
   ```toml
   # pyproject.toml of your plug-in package
   [project.entry-points."agentic_qa.plugins"]
   csv = "my_company.qa_plugins.csv_reader"
   ```

Importing the module is enough: the `@register` decorator does the rest. For local files, also
add the extension to `SUPPORTED_EXTS` in `ingest/sources/__init__.py` if folders should pick it up.
`tests/test_ingest.py::test_developer_can_add_a_reader_plugin` is a runnable version of this example.

### Recipe: OCR for scanned PDFs
Scanned pages are detected and reported (`PdfReader.min_chars_per_page`). To read them, write a
`reader` (or subclass `PdfReader`) that rasterises pages with `pdf2image` and runs `pytesseract`,
emitting `paragraph` blocks per text block. Register it under a new name with `extensions=(".pdf",)`
and higher priority than the built-in by registering it after the built-ins load (via `ingest.plugins`).
OCR text is lower quality: add a warning to `doc.warnings` so the confidence report reflects it.

### Recipe: a new source (e.g. Confluence, Box, an S3 bucket)
Subclass `Source`, set `priority` (lower = asked first), implement `can_handle` by URL pattern
and `fetch` to download into `dest`. Put auth settings under `sources.<name>` in settings.yaml;
they arrive as `self.settings`. Reuse `self.static_token()` for `token_env` / `token_command`.
Make the HTTP session injectable (see `GoogleDriveSource(session=...)`) so tests can simulate the API.

## 4. Client profiles instead of code

Most format differences between clients need **no code**: see `config/profiles/default.yaml`
(fully commented) and `config/profiles/example_client.yaml`.

| Need | Profile key |
|---|---|
| Client's own ID style | `id_patterns_extra: ['SR/\d{4}']` |
| Use cases called "Capability 3", "Epic 7" ... | `scenario_patterns_extra` (groups `kind`, `ord`) |
| Same scenario named differently in BRD and BRS | `scenario_aliases` |
| Header row not detected / wrong ID column | `sheets: {'Sheet name regex': {header_row: 4, id_column: 'Ref'}}` |
| Force a whole sheet into one scenario | `sheets: {'Payments.*': {scenario: 'Payments'}}` |
| Skip extra sheets | `skip_sheet_patterns`, or `sheets: {...: {skip: true}}` |
| One use case per file / per ID'd row | `segment_mode: whole_file` / `per_row` |
| Turn a detector or cleaner off / on | edit the `cleaners`, `scenario_finders`, `conflict_detectors` lists |
| Conflict sensitivity | `conflict_similarity_threshold` (0–1, higher = stricter) |

## 5. Changing agent behaviour

The four agents' instructions are plain Markdown in `qa_agents/prompts/`. Most quality
improvements are prompt changes; compare outputs before and after on the same inputs.
New agent or stage: follow `agents/base.py` (role prompt + typed input/output) and add it in
`orchestrator.Pipeline.run`. LLM providers: `core/llm.py`; agents under test: `core/target.py`;
bug trackers: `core/tracker.py`.

### The Requirement Troubleshooter (`qa_agents/troubleshoot/`)
* `index.py`: `RequirementIndex` loads a batch (`00_ingest/items.json`, conflicts, `SCN-*/02_testcases.json`) and
  searches it: exact requirement/test IDs first, then BM25 keyword ranking with light stemming. `coverage()`
  (rare words weigh more) decides found / not found; tune `Troubleshooter.min_keyword_coverage`.
* `agent.py`: the LLM receives only the passages found (S1..Sn) and must cite them; citations to anything
  else are removed. With the mock provider, or if the LLM call fails, a rule-based answer is returned.
* Prompt: `qa_agents/prompts/troubleshooter.md`. Model: `llm_overrides: {troubleshooter: {...}}`.
* Swap the search for embeddings / a vector database by replacing `RequirementIndex.search` (same `Hit` output).

### Application types (`qa_agents/core/apps.py`, `core/target.py`, `core/web.py`)
- `apps.resolve_app()` turns `app:` + `apps.<name>:` into the adapter config; `SYSTEM_KIND` tells the Test
  Designer what it is testing. Add a new application type by adding it to `APP_TYPES`, `SYSTEM_KIND` and
  either `TARGETS` (conversational: implement `converse(persona, target_agent, turns) -> [TargetResponse]`)
  or a browser adapter in `core/web.py` (implement `run_test(test, evidence_dir)` like `WebTarget`).
- Browser steps: `agents/web_steps.py` reads plain steps with regex rules; add a `@rule(...)` for a new
  phrasing. Steps no rule can read go to the AI (`prompts/automation_engineer_web.md`), else become manual.
- Finding elements: `WebTarget._find` = css= -> page map -> labels/roles/placeholders -> AI pick.
- Gen AI checks: `core/evaluator.py` (`GENAI_CRITERIA` for the AI judge, `HEURISTICS` offline,
  `PII_PATTERNS`). `AutomationEngineer.add_quality_checks` decides which tests get which check.

## 6. Tests

```
python -m pytest -q
```

* `tests/fixtures/samples/` holds real document structures (anonymise before adding). Each new
  client format that once broke the reader should get a fixture and an expected-result test.
* `tests/synthetic.py` builds layouts on the fly (multi-row records, merged cells, split PDF tables,
  custom IDs). Add new builders there rather than committing many binary files.
* Drive sources are tested against simulated APIs (`FakeSession`); no network or credentials needed.
* Real-API smoke tests for Drive/SharePoint need your accounts; run them manually.

## 7. Debugging a bad split

1. `python -m qa_agents preview --usecase <files>`: read the confidence reasons and the
   "How items were assigned" column.
2. Open `<batch>/00_ingest/items.json`: each item has `scenarios`, `assigned_by`
   (`explicit`, `heading`, `keyword`, `keyword-section`, `shared`, `front-matter`), `section` and `ref`.
3. Fix with a profile setting first; write a plug-in only if no setting covers it.
