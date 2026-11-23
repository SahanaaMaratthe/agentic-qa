# Installation guide

From zip to a working run in about 20 minutes. No coding needed: you copy commands into a
terminal and press Enter. Commands are the same on Windows and Mac except where marked.

## 1. Prerequisites

| Needed | Required for | Where |
|---|---|---|
| Windows 10/11 or macOS, 8 GB RAM, 1 GB free disk | everything | your laptop |
| Admin rights (or IT help) to install software | installing Python, VS Code | IT team |
| Python 3.10 or newer (3.12 recommended) | everything | https://www.python.org/downloads/ |
| VS Code (recommended editor) | opening files, terminal | https://code.visualstudio.com/ |
| Internet access to pypi.org | installing packages | office network / VPN (ask IT for proxy details if blocked) |
| An AI model key (Gemini API key or Vertex AI project) | real runs (not mock mode) | https://aistudio.google.com/ or your GCP admin |
| Google Cloud CLI `gcloud` | Gemini Enterprise target, Google Drive links | https://cloud.google.com/sdk/docs/install |
| Entra app registration (client ID) with read-only `Files.Read.All` + `Sites.Read.All` | SharePoint / OneDrive links | Microsoft 365 / Entra admin |
| Jira API token + sandbox project | filing bugs in Jira | https://id.atlassian.com/manage-profile/security/api-tokens |

Only the first five are needed to install and try the tool offline. Request the rest early;
approvals take time.

## 2. Install Python and VS Code

1. Run the Python installer. **Windows: tick "Add python.exe to PATH"** on the first screen.
   Mac: use `python3` / `pip3` wherever this guide says `python` / `pip`.
2. Install VS Code, open it, go to Extensions and install **Python** (by Microsoft).

## 3. Unzip and open the project

1. Unzip `agentic-qa.zip` to a short path without spaces, e.g. `C:\Projects\agentic-qa`
   (Windows) or `~/Projects/agentic-qa` (Mac). The folder must directly contain `README.md`
   and `qa_agents/`.
2. VS Code: **File > Open Folder** > choose that folder > trust it.
3. **Terminal > New Terminal**. All commands below are typed there.
4. Check: `python --version` shows 3.10 or higher.

## 4. Create the virtual environment and install packages

```bash
python -m venv .venv
```

Activate it (every time you open a new terminal):

| Terminal | Command |
|---|---|
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows Command Prompt | `.venv\Scripts\activate.bat` |
| Mac / Linux | `source .venv/bin/activate` |

The prompt now starts with `(.venv)`. If PowerShell says *running scripts is disabled*, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, answer `Y`, and activate again.

```bash
pip install -r requirements.txt
```

Then install only the extras you need:

| You want to | Install |
|---|---|
| Test websites / chat widgets (included in requirements.txt) | then once: `playwright install chromium` |
| Use Gemini as the AI model | `pip install google-genai` |
| Use Claude / OpenAI-compatible models | `pip install anthropic` / `pip install openai` |
| Read Google Drive links | `pip install google-auth google-auth-oauthlib` |
| Read SharePoint / OneDrive links | `pip install msal` |

## 5. Verify the installation

```bash
python -m pytest -q
```

Expected last line: **`80 passed, 1 skipped`** (the skipped one is the practice-portal browser test; it runs only if Playwright is installed, then you see `81 passed`). Then try the entry points (all offline, mock mode):

```bash
# a) the original short use case: 4 agents, 9 passed / 3 failed, 2 bug reports
python -m qa_agents run --usecase inputs/usecases/UC-001_rules_agent.md

# b) reading real BRD/BRS documents (the VTU samples): 2 scenarios, 26 conflicts, HIGH confidence
python -m qa_agents preview --usecase tests/fixtures/samples

# c) the web page: opens http://localhost:8501 in your browser (Ctrl+C in the terminal to stop)
python -m qa_agents ui

# d) the KVTU practice portal (a buggy web app to test): opens http://localhost:8600
python -m qa_agents demo-site

# e) web testing: with the portal running (d) in one terminal, in a SECOND terminal:
python -m qa_agents execute --testcases examples/kvtu_web/testcases.json --app web --headed
#    a browser opens and runs 14 test cases: 5 pass, 8 catch planted bugs, 1 is left for a human
```

Results are written to the `runs/` folder.

## 6. Connect the real systems (when ready)

All in `config/settings.yaml`; nothing else changes.

| Step | Settings block | Guide |
|---|---|---|
| Real AI model | `llm:` | README "Switching to real systems" |
| Which application you test | `app:` (web, chatbot, gemini_enterprise, genai, mock, none) and its block under `apps:` | README "Application types" |
| A website | `apps: web:` `base_url`, `page_map` | copy `config/pagemaps/kvtu_practice.yaml` |
| Gemini Enterprise agent under test | `apps: gemini_enterprise:` | README "Persona testing" |
| Design only (no execution) | `app: none` | stops after test design |
| Google Drive | `sources: gdrive:` | `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform` |
| SharePoint / OneDrive | `sources: sharepoint:` (`tenant_id`, `client_id`) | first run shows a sign-in code for https://microsoft.com/devicelogin |
| Jira | `tracker:` | keep `file_bugs: false` until you trust the triage |
| A client's document conventions | `config/profiles/<client>.yaml` | copy `example_client.yaml` |

Keep keys and tokens in environment variables, never in files you share:
PowerShell `$env:GEMINI_API_KEY="..."` · Mac `export GEMINI_API_KEY="..."`.

## 7. Updating to a new version

Updates come as a patch file (`.patch`). In the project folder, with your work committed:

```bash
git apply --check update.patch     # dry run: no output = it fits
git apply update.patch
pip install -r requirements.txt    # in case new packages were added
python -m pytest -q
git add . ; git commit -m "Apply update" ; git push
```

If `--check` reports a file you changed yourself (often `config/settings.yaml`), save your
copy, run `git checkout -- <that file>`, apply the patch, and copy your values back.

## 8. Troubleshooting

| You see | Fix |
|---|---|
| `'python' is not recognized` | Reinstall Python with "Add to PATH" ticked, or use `py` on Windows |
| `No module named qa_agents` | Your terminal is not in the project folder; open the folder in VS Code |
| `No module named pydantic` / `streamlit` / `pdfplumber` | Virtual environment not active: activate it (step 4) |
| pip SSL / connection errors | Office proxy: `pip install --proxy http://<proxy>:<port> -r requirements.txt` |
| `No module named 'google'` / `'msal'` | Install the extra from the table in step 4 |
| Tests fail with a `reportlab` error | `pip install reportlab` (used only by the tests) |
| Web page does not open | Go to http://localhost:8501 yourself; if the port is busy: `python -m qa_agents ui --port 8502` |
| Preview says confidence LOW | The documents' grouping was unclear; see `runs/batch_*/00_ingest/report.md` and use a client profile |
| `Google Drive: access denied` | Re-run the `gcloud ... login` command with the Drive scope, or check the file is shared with you |
| `SharePoint: access denied` | Ask IT to grant admin consent for the app's Files.Read.All / Sites.Read.All |
| `Browser testing needs Playwright` / `Executable doesn't exist` | `pip install playwright` then `playwright install chromium`; or set `browser: chrome` (or `msedge`) under `apps: web:` to use your installed browser |
| Web tests all `error` with `net::ERR_CONNECTION_REFUSED` | The website isn't running: for the practice portal start `python -m qa_agents demo-site` in another terminal |
| A web test is `error`: `could not find 'X'` | The step names a field or button differently from the screen. Fix the step's wording, or add `X: "css=..."` under `elements:` in the page map (see `learned_page_map.yaml` in the run folder) |
| A web test is `manual` | A step was too vague for the robot ("Observe the fee"). Run it by hand, or reword it ("Verify the page shows '₹150.00'") |

More help: `README.md` (features and settings), `docs/EXTENDING.md` (for developers).
