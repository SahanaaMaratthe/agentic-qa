"""agentic-qa web page (Streamlit). Start with:  python -m qa_agents ui

Runs only on this computer (http://localhost:8501). Uploaded files are saved under
runs/ and are sent nowhere except to the configured AI model as part of a run.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qa_agents import service  # noqa: E402
from qa_agents.core.apps import APP_TYPES, resolve_app  # noqa: E402
from qa_agents.ingest.scenarios import SHARED  # noqa: E402

UPLOAD_TYPES = ["xlsx", "xlsm", "pdf", "docx", "md", "txt"]


def _args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--settings", default="config/settings.yaml")
    a, _ = ap.parse_known_args(sys.argv[1:])
    return a


ARGS = _args()
st.set_page_config(page_title="agentic-qa", layout="wide")
ss = st.session_state
ss.setdefault("sid", uuid.uuid4().hex[:8])
ss.setdefault("preview", None)
ss.setdefault("outcome", None)
ss.setdefault("log", [])
ss.setdefault("chat", [])          # Troubleshooter conversation
ss.setdefault("ts", None)          # (batch_dir, Troubleshooter)

# ------------------------------------------------------------------ sidebar
settings = service.load_settings(ARGS.settings)
with st.sidebar:
    st.header("Settings")
    profiles = sorted(p.stem for p in Path("config/profiles").glob("*.yaml")) or ["default"]
    default_profile = (settings.get("ingest") or {}).get("profile", "default")
    profile = st.selectbox("Client profile", profiles, index=profiles.index(default_profile) if default_profile in profiles else 0,
                           help="Rules for this client's document formats (ID styles, scenario names, sheets to skip).")
    until = st.selectbox("Run the agents until", ["design", "report"], index=0,
                         format_func=lambda x: {"design": "Test design (test cases + gaps)",
                                                "report": "Full run (execute + bug reports)"}[x])
    st.divider()
    app_default = resolve_app(settings)["app"]
    apps = list(APP_TYPES)
    app = st.selectbox("Application under test", apps, index=apps.index(app_default),
                       format_func=lambda k: APP_TYPES[k],
                       help="What the Automation Engineer runs the tests against. Each type's connection details "
                            "(URL, page map, tokens) are in settings.yaml under `apps:`.")
    app_cfg = resolve_app(settings, app)
    headed = None
    if app == "web" or app_cfg.get("type") == "chat_widget":
        headed = st.checkbox("Show the browser while testing", value=not app_cfg.get("headless", True),
                             help="Ticked: a browser window opens and you watch every click (slower, good for learning). "
                                  "Unticked: runs hidden.")
        where = app_cfg.get("base_url") or app_cfg.get("url") or "(set base_url in settings.yaml)"
        st.caption(f"Website: `{where}`" + (f"  \nPage map: `{app_cfg['page_map']}`" if app_cfg.get("page_map") else ""))
        if "localhost:8600" in where:
            st.caption("This is the KVTU practice portal: start it first in a second terminal with "
                       "`python -m qa_agents demo-site`.")
    elif app in ("chatbot", "genai"):
        st.caption(f"Endpoint: `{app_cfg.get('url', '(set url in settings.yaml)')}` · mode **{app_cfg.get('mode', 'api')}**")
    if app in ("chatbot", "gemini_enterprise", "genai", "mock"):
        q = settings.get("quality_checks") or {}
        if q.get("enabled", True):
            st.caption("Gen AI quality checks: " + ", ".join(q.get("checks", ["no_pii", "not_toxic"]))
                       + " (+ grounded / injection checks where the test type needs them)")
    st.caption(f"AI model: **{settings.get('llm', {}).get('provider')}** · Settings file: `{ARGS.settings}`")

st.title("agentic-qa")
st.caption("Requirement Analyst → Test Designer → Automation Engineer → Defect Manager")

# ------------------------------------------------------------------ 1. inputs
st.subheader("1. Add documents")
c1, c2 = st.columns(2)
with c1:
    uploads = st.file_uploader("Upload BRD / BRS / use-case files", type=UPLOAD_TYPES, accept_multiple_files=True,
                               help="Excel, PDF, Word, Markdown or text. Add the BRD and its BRS together.")
with c2:
    links = st.text_area("…or paste Google Drive / SharePoint links or local paths (one per line)", height=120,
                         placeholder="https://drive.google.com/drive/folders/...\nhttps://contoso.sharepoint.com/:x:/s/QA/...\nC:\\BRDs\\client_abc")
    refs = st.text_area("Supporting material (optional, one per line)", height=68,
                        help="Extra context for the Requirement Analyst, e.g. a glossary. Any format or link.")

if st.button("Read documents (preview, no AI)", type="primary"):
    inputs = []
    if uploads:
        up_dir = ROOT / "runs" / "ui_uploads" / ss.sid
        up_dir.mkdir(parents=True, exist_ok=True)
        for f in uploads:
            p = up_dir / Path(f.name).name
            p.write_bytes(f.getvalue())
            inputs.append(str(p))
    inputs += [x.strip().strip('"') for x in links.splitlines() if x.strip()]
    references = [x.strip().strip('"') for x in refs.splitlines() if x.strip()] or None
    if not inputs:
        st.error("Add at least one file or link first.")
    else:
        with st.spinner("Reading documents ..."):
            try:
                ss.preview = service.preview(inputs, ARGS.settings, profile, references, log=lambda *_: None)
                ss.outcome = None
                ss.chat, ss.ts = [], None
            except Exception as e:  # noqa: BLE001 - show any reading problem to the user
                ss.preview = None
                st.error(f"Could not read the documents: {e}")

with st.expander("…or run test cases you already have (skip reading and design)"):
    st.caption("Upload a `02_testcases.json` from an earlier run, or a file in the same format such as "
               "`examples/kvtu_web/testcases.json`. The Automation Engineer runs them against the application chosen "
               "on the left, and the Defect Manager reports the failures.")
    tc_file = st.file_uploader("Test cases (.json)", type=["json"], key="tc_json")
    if st.button("Run these test cases", disabled=tc_file is None):
        up = ROOT / "runs" / "ui_uploads" / ss.sid
        up.mkdir(parents=True, exist_ok=True)
        f = up / Path(tc_file.name).name
        f.write_bytes(tc_file.getvalue())
        ss.log = []
        with st.status("Automation Engineer and Defect Manager working ...", expanded=True) as status:
            def log2(*parts):
                line = " ".join(str(x) for x in parts).strip()
                if line:
                    st.write(line)
            try:
                summ = service.run_testcases(str(f), ARGS.settings, app, headed, log=log2)
                ss.outcome = service.BatchOutcome(batch_dir=Path(summ["run_dir"]).parent, runs=[summ])
                status.update(label="Done", state="complete")
            except Exception as e:  # noqa: BLE001
                status.update(label="Failed", state="error")
                st.error(str(e))

# ------------------------------------------------------------------ 2. preview
pv = ss.preview
if pv:
    r = pv.result.report
    st.subheader("2. Check what was found")
    msg = {"high": st.success, "medium": st.warning, "low": st.error}[r.confidence]
    msg(f"Reading confidence: **{r.confidence.upper()}**" +
        ("" if pv.ok else " — the agents will not start unless you tick *Run anyway* below."))
    for reason in r.confidence_reasons:
        st.write(f"- {reason}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Documents", len(r.documents))
    m2.metric("Use cases (scenarios)", len(pv.result.packages))
    m3.metric("Conflicts between sources", len(r.conflicts))
    m4.metric("Shared items", sum(SHARED in it.scenarios for it in pv.result.items))

    st.markdown("**Documents**")
    st.dataframe(pd.DataFrame([{
        "File": d["name"], "Type": d["role"].upper(), "Format": d["format"], "Doc ID": ", ".join(d["doc_ids"]),
        "Traces to": ", ".join(d["traces_to"]), "Items": d["items"], "With ID": d["items_with_id"],
        "Assignment": ", ".join(f"{k}: {v}" for k, v in sorted(d["assignment"].items()))} for d in r.documents]),
        hide_index=True, width="stretch")

    st.markdown("**Use cases to generate tests for** (untick any you don't want)")
    rows = [{"Run": True, "Key": p.scenario.key, "Name": p.scenario.name,
             "Items": sum(p.scenario.key in it.scenarios for it in p.items),
             "Conflicts": len(p.conflicts), "Found in": len(p.scenario.found_in)} for p in pv.result.packages]
    picked = st.data_editor(pd.DataFrame(rows), hide_index=True, width="stretch",
                            disabled=["Key", "Name", "Items", "Conflicts", "Found in"], key="pick")
    for p in pv.result.packages:
        with st.expander(f"View the use case text for {p.scenario.key}: {p.scenario.name}"):
            st.markdown(p.text)

    if r.conflicts:
        st.markdown("**Conflicts between sources** (each becomes a gap for the BA)")
        st.dataframe(pd.DataFrame([{"ID": c.id, "Kind": c.kind, "Confidence": c.confidence,
                                    "Description": c.description, "Question for BA": c.question} for c in r.conflicts]),
                     hide_index=True, width="stretch")
    if r.warnings:
        with st.expander(f"Warnings ({len(r.warnings)})"):
            for w in r.warnings:
                st.write(f"- {w}")
    st.download_button("Download preview report (.md)", pv.report_md, file_name="ingest_preview.md")

    # -------------------------------------------------------------- 3. run
    st.subheader("3. Run the agents")
    force = False
    if not pv.ok:
        force = st.checkbox("Run anyway (I checked the preview and the split is acceptable)")
    selected = [row["Key"] for _, row in picked.iterrows() if row["Run"]]
    if st.button(f"Run for {len(selected)} use case(s)", type="primary", disabled=not selected or (not pv.ok and not force)):
        ss.log = []
        with st.status("Agents working ...", expanded=True) as status:
            def log(*parts):
                line = " ".join(str(p) for p in parts).strip()
                if line:
                    ss.log.append(line)
                    st.write(line)
            try:
                ss.outcome = service.run_batch(pv, ARGS.settings, selected, until, force, log=log, app=app, headed=headed)
                status.update(label="Done", state="complete")
            except Exception as e:  # noqa: BLE001
                status.update(label="Failed", state="error")
                st.error(str(e))

# ------------------------------------------------------------------ 4. results
out = ss.outcome
if out:
    st.subheader("4. Results")
    st.caption(f"All files are in `{out.batch_dir}`")
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if getattr(out, "workbook", None) and Path(out.workbook).exists():
        st.download_button(f"Download all test cases as Excel ({len(out.runs)} use case(s))",
                           Path(out.workbook).read_bytes(), file_name=Path(out.workbook).name, mime=XLSX,
                           type="primary", key="dl_all_xlsx",
                           help="Summary, test cases per use case, gaps for the BA, traceability and glossary. "
                                "Opens in Excel, Google Sheets (Drive) and Excel Online (SharePoint).")
    for run in out.runs:
        rd = Path(run["run_dir"])
        st.markdown(f"### {run.get('scenario', rd.name)}")
        tabs = st.tabs(["Test cases", "Quality", "Gaps & conflicts", "Execution", "Bugs"])
        csv = rd / "02_testcases.csv"
        with tabs[0]:
            if csv.exists():
                df = pd.read_csv(csv, encoding="utf-8-sig").fillna("")
                order = ["Critical", "High", "Medium", "Low"]
                f1, f2 = st.columns(2)
                if "Priority" in df.columns:
                    counts = df["Priority"].value_counts()
                    st.caption(" · ".join(f"{p}: {counts.get(p, 0)}" for p in order) + "  (most important first)")
                    pick = f1.multiselect("Priority", order, default=order, key=f"pr_{rd}")
                    df = df[df["Priority"].isin(pick)]
                if "Perspective" in df.columns:
                    views = ["End user", "Business", "Both"]
                    pick_v = f2.multiselect("Perspective", views, default=views, key=f"pe_{rd}")
                    df = df[df["Perspective"].isin(pick_v)]
                st.dataframe(df, hide_index=True, width="stretch")
                xl = rd / "02_testcases.xlsx"
                d1, d2 = st.columns(2)
                if xl.exists():
                    d1.download_button("Download this use case as Excel", xl.read_bytes(),
                                       file_name=f"{rd.name}_test_cases.xlsx", mime=XLSX, key=f"dl_xl_{rd}")
                d2.download_button("Download as CSV", csv.read_bytes(), file_name=f"{rd.name}_testcases.csv",
                                   key=f"dl_tc_{rd}")
        with tabs[1]:
            q = rd / "02_quality.md"
            st.markdown(q.read_text(encoding="utf-8") if q.exists() else "_No quality report._")
        with tabs[2]:
            g = rd / "02_gaps.md"
            if g.exists():
                st.markdown(g.read_text(encoding="utf-8"))
                st.download_button("Download gap report (.md)", g.read_bytes(), file_name=f"{rd.name}_gaps.md",
                                   key=f"dl_gap_{rd}")
        with tabs[3]:
            sm = rd / "03_summary.md"
            st.markdown(sm.read_text(encoding="utf-8") if sm.exists() else "_Not executed (stopped after test design)._")
            res_file = rd / "03_results.json"
            if res_file.exists():
                import json as _json
                for res in _json.loads(res_file.read_text(encoding="utf-8")):
                    logs = res.get("steps_log") or []
                    if not logs or res.get("status") == "passed":
                        continue
                    with st.expander(f"{res['test_id']}: {res['status']} - what the browser did"):
                        for line in res.get("turns", []):
                            st.write(("❌ " if "->" in line else "✔️ ") + line)
                        if res.get("error"):
                            st.caption(res["error"])
                        for x in logs:
                            if x.get("screenshot") and (x.get("status") == "failed" or x["screenshot"].endswith("final.png")):
                                if Path(x["screenshot"]).exists():
                                    st.image(x["screenshot"], caption=Path(x["screenshot"]).name)
        with tabs[4]:
            bugs = sorted((rd / "bugs").glob("*.md")) if (rd / "bugs").exists() else []
            if not bugs:
                st.write("_No bug reports._")
            for b in bugs:
                with st.expander(b.stem):
                    import re as _re
                    text = b.read_text(encoding="utf-8")
                    st.markdown(_re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text))      # images shown below instead
                    for rel in _re.findall(r"!\[[^\]]*\]\(([^)]*)\)", text):
                        img = (b.parent / rel).resolve()
                        if img.exists():
                            st.image(str(img), caption=img.name)


# ------------------------------------------------------------------ 5. troubleshooter
def _troubleshooter():
    pv_ = ss.preview
    if ss.ts is None or ss.ts[0] != pv_.batch_dir:
        ss.ts = (pv_.batch_dir, service.make_troubleshooter(pv_.batch_dir, ARGS.settings, profile))
    ts_ = ss.ts[1]
    ts_.index.refresh_tests()          # picks up test cases generated after the preview
    return ts_


def _show_answer(a):
    if a.found:
        st.success("Found in the requirement documents")
    else:
        st.warning("Not stated in the requirement documents")
    st.markdown(a.answer)
    if a.sources:
        st.markdown("**Where it is written**" if a.found else "**Closest related requirements**")
        st.dataframe(pd.DataFrame([{"Ref": s.ref, "ID": s.item_id or "", "Location": s.label,
                                    "Text": s.text if len(s.text) < 300 else s.text[:299] + "…"}
                                   for s in (a.sources[:5] if a.found else a.sources[:3])]),
                     hide_index=True, width="stretch")
    if a.found:
        st.markdown("**Related test cases**")
        if a.related_tests:
            st.dataframe(pd.DataFrame([{"Test": t.id, "Use case": t.scenario, "Title": t.title, "Why related": t.why}
                                       for t in a.related_tests]), hide_index=True, width="stretch")
        elif not a.tests_available:
            st.caption("No test cases generated for these documents yet. Run the agents (step 3) and ask again.")
        else:
            st.caption("No generated test case covers this requirement: a coverage gap.")
    if a.conflicts:
        with st.expander(f"Conflicts between documents about this ({len(a.conflicts)})", expanded=len(a.conflicts) <= 3):
            for c in a.conflicts:
                st.write(f"- {c}")
    if a.gaps:
        with st.expander(f"Open gaps ({len(a.gaps)})"):
            for g in a.gaps:
                st.write(f"- {g}")
    st.markdown(f"**Impact if this stays unresolved:** {a.impact}")
    st.markdown(f"**Suggested next step:** {a.suggestion}")
    if a.mode == "offline":
        st.caption("Answered without an AI model (mock mode / fallback): exact text and locations are shown as found.")


if ss.preview:
    st.subheader("5. Ask the Requirement Troubleshooter")
    st.caption("Not sure where a requirement is written, what it says, or what it means for your tests? Ask here. "
               "Answers come only from the documents read in step 2, with file and sheet/row or page.")
    for q, a in ss.chat:
        with st.chat_message("user"):
            st.write(q)
        with st.chat_message("assistant"):
            _show_answer(a)
    question = st.chat_input("e.g. Where is the OTP expiry rule written?  What does BR-GRV-02 say?  "
                             "Which requirement is TC-SCN-01-004 based on?")
    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("Searching the requirement documents ..."):
                try:
                    ans = _troubleshooter().ask(question)
                    ss.chat.append((question, ans))
                    _show_answer(ans)
                except Exception as e:  # noqa: BLE001
                    st.error(f"Could not answer: {e}")
