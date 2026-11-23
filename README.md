# agentic-qa: a multi-agent test system for enterprise AI agents

Four agents take a use case (even a 3-line one) through to filed bugs:

| Agent | Role | Input | Output |
|---|---|---|---|
| **Requirement Analyst** | Understands the use case and recovers unstated requirements | `inputs/usecases/*.md` (+ optional BRD extract) | `01_understanding.json` |
| **Test Designer** | Writes test cases from the end-user and business viewpoints, prioritised Critical → Low, in plain language; flags gaps; a rule-based review sends unclear tests back once for fixing | understanding + `config/testcase_skeleton.yaml` + `config/glossary.yaml` | `02_testcases.json/.csv`, `02_gaps.md`, `02_quality.md` |
| **Automation Engineer** | Converts test cases to executable checks and runs them per persona | test cases | `03_executable_suite.json`, `03_results.json`, `03_junit.xml`, `03_summary.md` |
| **Defect Manager** | Triages failures (bug / test defect / env / review) and writes or files bugs | results | `04_triage.md`, `bugs/*.md`, Jira tickets (optional) |
| **Requirement Troubleshooter** | Answers QA's questions about where a requirement is written, its related tests and the impact of leaving it unclear | read documents + generated tests | chat answers on the web page |

```
use case ─▶ Requirement Analyst ─▶ Test Designer ─▶ [human review of gaps] ─▶ Automation Engineer (convert + execute) ─▶ Defect Manager ─▶ Markdown / Jira
```

Agents never call each other directly; the orchestrator hands typed JSON artifacts between
them (`qa_agents/core/models.py`). Any stage can be rerun, edited by hand, or replaced.

## Quick start (offline, no keys)

```bash
pip install -r requirements.txt
python -m qa_agents run --usecase inputs/usecases/UC-001_rules_agent.md
python -m pytest -q
```

Mock mode uses canned LLM outputs (`fixtures/mock_llm/`) and a fake school agent
(`fixtures/mock_kb.yaml`) with two seeded defects: a staff-only document leaking to students,
and a hallucinated number. The run finds both, and Defect Manager also flags an over-strict
assertion as a *test defect*, not a product bug.

## Reading BRD / BRS documents in any format

Give the tool your requirement documents as they are: Excel, PDF (typed), Word, Markdown or
text, local or on Google Drive / SharePoint / OneDrive. It finds the **scenarios** (one use case
each), pairs a BRD with its BRS, and reports **conflicts between sources** as gaps for the BA.

```bash
# 1. check what it found (no AI calls, free, seconds)
python -m qa_agents preview --usecase BRD.xlsx --usecase BRS.pdf
# 2. generate test cases + gap reports for every scenario (or pick some with --scenarios SCN-01)
python -m qa_agents run --usecase BRD.xlsx --usecase BRS.pdf --until design
# folders and links work too
python -m qa_agents run --usecase "https://drive.google.com/drive/folders/<id>" --until design
python -m qa_agents run --usecase "https://contoso.sharepoint.com/:f:/s/QA/<share-id>" --until design
# a client whose documents follow other conventions
python -m qa_agents preview --usecase docs/ --profile client_abc
```

**Web page:** `python -m qa_agents ui` opens http://localhost:8501 (on your computer only):
upload files or paste links → check the preview → tick the use cases → run → view and download results.

**Requirement Troubleshooter (web page, section 5):** a chat box where QA asks things like
*"Where is the OTP expiry rule written?"*, *"What does BR-GRV-02 say?"* or *"Which requirement is
TC-SCN-01-004 based on?"*. Every answer shows the exact file and sheet/row or page, the related
test cases, conflicts between documents, the impact on testing if the doubt stays unresolved, and
a next step. If something is not in the documents it says so and suggests a gap for the BA. Answers
come only from the documents (search is rule-based; the AI only explains what was found and cannot
cite anything else), and it also works without an AI model.

Output: `runs/batch_<time>/00_ingest/` (what was read: `report.md`, one `SCN-xx.md` use case per
scenario) and one folder per scenario with the usual agent outputs.

**Confidence:** HIGH / MEDIUM continue; LOW (e.g. many requirements but no way to group them)
stops before any AI call. Fix it with a client profile, or use `--force` / "Run anyway".

**Formats a client sends differently** are handled in `config/profiles/<client>.yaml`
(ID styles, scenario names, header rows, sheets to skip). See `example_client.yaml`.
Scanned PDFs and old `.doc` / `.xls` files are reported, not read.

**Drive access** (`sources:` in settings.yaml, read-only):
- Google Drive: `auth: adc` (your account, after `gcloud auth application-default login --scopes=...drive.readonly,...cloud-platform`), `oauth`, or `service_account`
- SharePoint / OneDrive: `auth: device_code` (your account; needs an Entra app registration `client_id` with Files.Read.All / Sites.Read.All) or `client_secret` for unattended runs

**Portal-style requirements** (no chatbot to call): set `target: {type: none}` and the run stops after test design.

Developers: see **[docs/EXTENDING.md](docs/EXTENDING.md)** for the plug-in architecture.

## Practice portal (a buggy app to test against)

`python -m qa_agents demo-site` opens the **KVTU practice portal**, a fictional university portal built from the
requirements in `demo_site/requirements/` (document requests, payments, grievances, staff desks, MIS).
It has 59 planted bugs, a reference build with all bugs switched off, a QA panel (clock, outbox, test files)
and an answer key. See `demo_site/README.md`.

## Application types: choose what you are testing

| `app:` | What it is | How the Automation Engineer tests it |
|---|---|---|
| `web` | Website / web portal | A real browser (Playwright) performs each step: open pages, type, choose, click, upload, then checks the texts on screen. Screenshot per step. |
| `chatbot` | Chatbot | `mode: api`: REST calls (like Postman). `mode: widget`: types into the chat box on a web page and reads the bot's bubbles. |
| `gemini_enterprise` | Gemini Enterprise agent | `streamAssist` with `agentsSpec` routing, one identity per persona, sessions for multi-turn |
| `genai` | Gen AI app behind an API | `mode: llm` (one input, one output) or `mode: rag` (returns its source passages); `provider: openai_compatible` for Azure OpenAI / vLLM / Ollama |
| `mock` | Built-in demo chatbot | offline, no keys |
| `none` | Design only | test cases and gaps; nothing executed |

```bash
python -m qa_agents run --usecase demo_site/requirements --app web --headed   # design + run in a visible browser
python -m qa_agents execute --testcases examples/kvtu_web/testcases.json --app web --headless
python -m qa_agents resume --run-dir runs/SCN-01_... --from automate --app web
```

**Web testing.** Steps are read the way testers write them ("Enter '1KV21CS001' in the USN
field", "Click 'Send OTP'", "Verify the page shows 'Payment successful'"); quoted texts in the
expected result become on-screen checks. Fields are found in this order: `css=` selectors, the
**page map** (`config/pagemaps/*.yaml`: page names, field selectors, persona sign-in steps),
the live page's labels / button texts / placeholders, and finally the **AI** picking from the
page's elements (with a real model). What it finds by reading the page is saved to
`learned_page_map.yaml` in the run folder. Steps it cannot automate are marked **manual**.
Each run writes `screenshots/<test>/`; bug reports and Jira tickets get the failing screenshot.
`headless: false` / `--headed` shows the browser; `slow_mo_ms` slows it down to watch.
Test files for upload checks are generated: `generate:big.pdf:5.3MB`, `generate:fake.pdf:text`.
In mock mode (no AI model) the Test Designer always returns the built-in school chatbot test cases,
so to see web testing offline use `execute` with `examples/kvtu_web/testcases.json`; with a real
model, `run --app web` designs web test cases from your BRD/BRS and executes them.

**Gen AI quality checks** (`quality_checks:` in settings), added to every test on an AI app:
`grounded` (every fact is in the source passages, no hallucination), `not_toxic`, `unbiased`,
`no_pii` (phone, e-mail, Aadhaar, PAN, card numbers), `resists_injection`. With a real model an
AI judge decides; in mock mode simple rules do. `critical: false` reports them without failing
the test. The Test Designer also writes safety, fairness and prompt-injection tests for AI apps,
and boundary and accessibility tests for web apps.

## Switching to real systems: edit `config/settings.yaml` only

**1. LLM for the agents**: `provider: gemini | anthropic | openai | mock`. `openai` also
covers Azure OpenAI, Ollama, vLLM etc. via `base_url`. You can give different models to
different agents with `llm_overrides`, and use a separate `judge_llm` for semantic checks.

**2. Application under test**: `app:` picks one block under `apps:` (or `--app` on the command
line, or the dropdown on the web page). See "Application types" below.

**3. Bug tracker**: `markdown` (default) or `jira` (Cloud or Server/DC, REST v2,
dedupes by test-id label, comments on an existing open bug instead of creating a duplicate).
Keep `file_bugs: false` until you trust the triage.

## Persona testing on Gemini Enterprise (important)

Gemini Enterprise enforces the **SharePoint permissions of the calling user**. To really test
"a student must not see the Staff Handbook", each persona needs **its own test identity**
(e.g. `qa.student@school.edu`, `qa.ntstaff@school.edu`) in your IdP, with the right SharePoint
groups. Configure one token per persona under `target.personas_auth`
(`token_env` or `token_command`). A single service account for all personas tests nothing about
access control. Test Designer raises this as a gap (G-05) for exactly this reason.

## How test cases are written

* **Priority:** Critical / High / Medium / Low = how bad if it fails × how likely. Critical = data leak, money,
  compliance, core journey blocked. Every level is covered; the list is sorted and renumbered so
  `TC-…-001` is always the most important.
* **Perspective:** End user (real journeys, mistakes, informal language, accessibility) or Business
  (rules, money, compliance, SLAs, reputation) or Both; both viewpoints are always covered.
* **Readable by everyone:** each test has a plain-language *Purpose*, *Why this priority* and *Business impact*;
  abbreviations are spelled out on first use (from `config/glossary.yaml`: add your client's terms there);
  no technical jargon; one action per step; observable expected results.
* **Quality review:** `02_quality.md` shows priority / perspective counts and any remaining issues (vague
  results, unexplained abbreviations, long steps). Steps are typed messages for a chatbot, or screen actions
  when `target: type: none` (portals).

## Excel workbooks (for Google Drive / SharePoint)

Every run writes `02_testcases.xlsx` (per use case) and batches also write `test_cases_<batch>.xlsx`
(one test-case sheet per use case). Upload either to Google Drive (opens as Google Sheets) or
SharePoint / OneDrive (opens in Excel Online). The web page has download buttons.

| Sheet | Contents |
|---|---|
| Summary | Counts by priority, perspective, gaps, uncovered requirements, automated pass/fail; how to read the file |
| Test Cases (or `TC SCN-xx`) | Your template's columns, Critical first, colour-coded, filters, frozen header; plus **Status** (dropdown: Not run / Pass / Fail / Blocked / Not applicable), Actual Result, Tested By, Test Date, Comments. Automated runs pre-fill Status, and Comments carry the Defect Manager's verdict and bug ID |
| Gaps & Conflicts | Questions for the BA with **BA Answer** and **Status** (Open / Answered / Closed) columns to fill |
| Traceability (RTM) | Requirement ID → covering test cases, highest priority, and **NOT COVERED** in red |
| Glossary | Abbreviations used, spelled out |

Edited `02_testcases.json` by hand? Rebuild the workbook: `python -m qa_agents export --run-dir runs/<folder>`.

## Your test-case skeleton

Edit `config/testcase_skeleton.yaml`: rename, reorder or add columns. Custom columns use
`field: extra.<name>` with a description, and Test Designer fills them in. The CSV export follows
your column order (opens directly in Excel).

## Recommended workflow

1. `run --usecase UC.md --review` pauses after Test Designer. Review `02_gaps.md` with the BA, and edit
   `02_testcases.json` if needed (fill real expected values for `missing_test_data` gaps).
2. `resume --run-dir runs/UC-... --from automate` generates and executes.
3. Check `03_executable_suite.json` once and commit the approved run folder (e.g. `approved/UC-001`).
4. Regression: `resume --run-dir approved/UC-001 --from execute --fail-on-bugs` in CI
   (see `.github/workflows/agent-qa.yml`; the same command works in Jenkins/GitLab/Azure DevOps).
5. Set `run.repeats: 3` to catch flaky (non-deterministic) answers.

Run a whole folder: `run --usecase inputs/usecases/`.

## Assertion types (Automation Engineer)
`contains_all`, `contains_any`, `not_contains` (leak checks), `regex`, `refusal`,
`cites_source`, `semantic` (LLM judge), `max_latency_ms`, and the Gen AI checks `grounded`,
`not_toxic`, `unbiased`, `no_pii`, `resists_injection`. Web tests use browser actions
(`goto`, `fill`, `select`, `check`, `click`, `upload`, `expect_text`, `expect_no_text`, ...). Deterministic guardrails in
`AutomationEngineer._harden` stop the LLM from altering the test's prompts or persona, and add a
refusal check to denial-type access tests.

## Project layout
```
config/            settings, domain context, personas, test-case skeleton
config/profiles/   client profiles for reading documents (default.yaml, example_client.yaml)
config/pagemaps/   page maps for web apps (kvtu_practice.yaml)
examples/          ready-to-run test suites (kvtu_web/testcases.json)
inputs/usecases/   short use cases ("# UC-001: Title" on the first line)
qa_agents/
  ingest/          reading documents: sources, readers, cleaners, scenarios, conflicts, pipeline
  core/            models (contracts), llm, target, tracker, evaluator adapters
  agents/          requirement_analyst, test_designer, automation_engineer, defect_manager
  prompts/         one role prompt per agent (edit to tune behaviour)
  ui/              the web page (Streamlit)
  service.py       public API used by the CLI and the web page
  orchestrator.py, __main__.py
docs/EXTENDING.md  developer guide (plug-ins, profiles, tests)
demo_site/         KVTU practice portal: static web app with planted bugs, answer key, KVTU BRD/BRS
fixtures/          mock LLM outputs + mock knowledge base
tests/             unit, end-to-end and document-reading regression tests (+ fixtures/samples)
```

## Extending
- **Other agents** (hostel, curriculum): add use-case files and map their names in `target.agents`.
  Domain knowledge lives in `config/domain_context.md`, not in code.
- **Framework hosting**: each agent is a plain class with `run()`, so it can be wrapped as a
  Google ADK agent, an A2A service, an MCP tool or a LangGraph node without changing logic.
- **More trackers**: subclass `BugTracker` (Azure DevOps, GitHub Issues, ServiceNow).
