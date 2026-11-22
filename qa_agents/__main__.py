"""Command line.

  # documents in any supported format, local or on a drive -> one use case per scenario
  python -m qa_agents preview --usecase BRD.xlsx --usecase BRS.pdf
  python -m qa_agents run     --usecase BRD.xlsx --usecase "https://drive.google.com/drive/folders/..."
  python -m qa_agents run     --usecase docs/ --scenarios SCN-01 --until design --profile client_abc

  # the original short use-case files still work exactly as before
  python -m qa_agents run  --usecase inputs/usecases/UC-001_rules_agent.md
  python -m qa_agents run  --usecase UC.md --review              # pause after gaps for human review
  python -m qa_agents resume --run-dir runs/UC-001_... --from automate

  # Excel workbook (written automatically; rebuild after editing 02_testcases.json by hand)
  python -m qa_agents export --run-dir runs/batch_...

  # web page
  python -m qa_agents ui
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from .orchestrator import STAGES, Pipeline


def interactive_review(design, run_dir: Path) -> bool:
    print(f"\n--- Review gate: {len(design.gaps)} gap(s) ---")
    for g in design.gaps:
        print(f"  {g.id} [{g.type.value}] {g.description}\n      Q: {g.question_for_ba}\n      Assumed: {g.assumed_resolution}")
    print(f"\nEdit {run_dir/'02_testcases.json'} if needed.")
    return input("Continue to automation? [y/N] ").strip().lower() == "y"


def _legacy_files(inputs: list[str]) -> list[Path] | None:
    """Short '# UC-001: Title' markdown use cases (file or folder of them) keep the original fast path."""
    files: list[Path] = []
    for i in inputs:
        p = Path(i)
        if p.is_dir():
            files += sorted(x for x in p.iterdir() if x.is_file())
        elif p.is_file():
            files.append(p)
        else:
            return None                       # a link or glob -> ingest
    if not files:
        return None
    for f in files:
        if f.suffix.lower() not in (".md", ".txt") or f.stat().st_size > 20_000:
            return None
        first = f.read_text(encoding="utf-8", errors="replace").lstrip().splitlines()[:1]
        if not first or not re.match(r"#\s*[A-Za-z]+-[\w-]+\s*[:\-]", first[0]):
            return None
    return files


def serve_demo_site(port: int, open_browser: bool = True) -> int:
    """Serve demo_site/ on localhost only. Stop with Ctrl+C."""
    import functools, http.server, threading, webbrowser
    root = Path(__file__).resolve().parent.parent / "demo_site"
    if not (root / "index.html").is_file():
        print(f"ERROR: practice site not found at {root}")
        return 2
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    handler = functools.partial(Quiet, directory=str(root))
    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        print(f"ERROR: port {port} is busy. Try: python -m qa_agents demo-site --port {port + 1}")
        return 2
    url = f"http://localhost:{port}/index.html"
    print(f"KVTU practice portal running at {url}\n  QA panel:   {url}#/qa\n  Answer key: {root / 'ANSWER_KEY.md'} (spoilers!)\nPress Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        httpd.server_close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="qa_agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="read documents / use cases and run the agents")
    pv = sub.add_parser("preview", help="read and split documents only (no AI): check scenarios, conflicts, confidence")
    for p in (r, pv):
        p.add_argument("--usecase", action="append", required=True,
                       help="file, folder, Google Drive or SharePoint link; repeat for several (e.g. BRD + BRS)")
        p.add_argument("--reference", action="append", help="supporting material (any format / link); repeatable")
        p.add_argument("--profile", help="client profile name in config/profiles/ (default: settings ingest.profile)")
    r.add_argument("--until", choices=STAGES, default="report")
    r.add_argument("--review", action="store_true", help="pause after Test Designer for human gap review")
    r.add_argument("--scenarios", help="comma-separated scenario keys to run, e.g. SCN-01,SCN-03 (default: all)")
    r.add_argument("--force", action="store_true", help="run even if reading confidence is LOW")
    s = sub.add_parser("resume", help="continue an existing run from a stage")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--from", dest="start", choices=STAGES, required=True)
    s.add_argument("--until", choices=STAGES, default="report")
    x = sub.add_parser("export", help="(re)build the Excel workbook for a run or batch folder")
    x.add_argument("--run-dir", required=True, help="runs/UC-001_... or runs/batch_...")
    u = sub.add_parser("ui", help="open the web page (runs locally on this computer)")
    u.add_argument("--port", default="8501")
    d = sub.add_parser("demo-site", help="open the KVTU practice portal (a buggy web app to test against)")
    d.add_argument("--port", type=int, default=8600)
    d.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    for p in (r, s, pv, u, x):
        p.add_argument("--settings", default="config/settings.yaml")
    for p in (r, s):
        p.add_argument("--fail-on-bugs", action="store_true", help="exit 1 if any product bug is found (CI)")
    a = ap.parse_args(argv)

    if a.cmd == "demo-site":
        return serve_demo_site(a.port, not a.no_browser)

    if a.cmd == "ui":
        app = Path(__file__).resolve().parent / "ui" / "app.py"
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), "--server.port", a.port,
                                "--server.address", "localhost", "--", "--settings", a.settings])

    from . import service

    if a.cmd == "export":
        return 0 if service.export_excel(Path(a.run_dir), a.settings) else 2

    summaries = []
    if a.cmd == "resume":
        summaries.append(Pipeline(a.settings).run(Path(a.run_dir), start=a.start, stop=a.until))
    elif a.cmd == "run" and (legacy := _legacy_files(a.usecase)) is not None:
        ref = ""
        if a.reference:
            pv0 = service.preview(a.reference, a.settings, a.profile)
            ref = service.render_document_text(pv0.result)
        for f in legacy:
            summaries.append(service.run_legacy(str(f), a.settings, a.until, ref,
                                                interactive_review if a.review else None))
    else:
        try:
            pv_ = service.preview(a.usecase, a.settings, a.profile, a.reference)
        except service.IngestError as e:
            print(f"\nERROR: {e}")
            return 2
        print("\n" + pv_.report_md)
        print(f"(saved to {pv_.batch_dir / '00_ingest'})")
        if a.cmd == "preview":
            return 0 if pv_.ok else 2
        if not pv_.ok and not a.force:
            print("\nReading confidence is LOW: agents were NOT started. Fix the client profile or use --force.")
            return 2
        sel = [x.strip() for x in a.scenarios.split(",")] if a.scenarios else None
        try:
            out = service.run_batch(pv_, a.settings, sel, a.until, a.force, interactive_review if a.review else None)
        except service.IngestError as e:
            print(f"\nERROR: {e}")
            return 2
        summaries = out.runs
    print("\n" + json.dumps(summaries, indent=2))
    if getattr(a, "fail_on_bugs", False) and any(s.get("bugs") for s in summaries):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
