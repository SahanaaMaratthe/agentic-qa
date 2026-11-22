"""Practice portal: every planted bug shows up in the practice build and not in the reference build.

Needs Playwright with a Chromium browser (pip install playwright && playwright install chromium).
Skipped automatically when that is not installed, so the main test suite never depends on a browser."""
import functools, http.server, json, os, threading
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent / "demo_site"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def results():
    pw = pytest.importorskip("playwright.sync_api")
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(ROOT)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/index.html"
    out = {}
    try:
        with pw.sync_playwright() as p:
            try:
                exe = os.environ.get("QA_CHROME")  # optional: path to an installed Chrome/Edge
                browser = p.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe else p.chromium.launch()
            except Exception as e:  # browser binaries not installed
                pytest.skip(f"Chromium not available for Playwright: {e}")
            page = browser.new_page()
            page.on("dialog", lambda d: d.dismiss())
            page.goto(url + "#/")
            page.add_script_tag(path=str(ROOT / "tests" / "checks.js"))
            for mode in ("buggy", "correct"):
                out[mode] = page.evaluate("""async (mode) => { const r = {};
                    for (const id of Object.keys(CHECKS)) { H.reset(mode);
                      try { r[id] = JSON.stringify(await CHECKS[id]()); } catch (e) { r[id] = 'ERR ' + e.message; } }
                    return r; }""", mode)
            browser.close()
    finally:
        httpd.shutdown()
    return out


def test_answer_key_is_complete():
    key = json.loads((ROOT / "answer_key.json").read_text(encoding="utf-8"))["bugs"]
    ids = [b["id"] for b in key]
    assert len(ids) == len(set(ids)) >= 40
    js = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "js").glob("*.js"))
    for i in ids:
        assert f'"{i}"' in js, f"{i} is in the answer key but not wired into the site"


def test_every_bug_differs_between_builds(results):
    key = json.loads((ROOT / "answer_key.json").read_text(encoding="utf-8"))["bugs"]
    for b in key:
        practice, reference = results["buggy"][b["id"]], results["correct"][b["id"]]
        assert not practice.startswith("ERR") and not reference.startswith("ERR"), (b["id"], practice, reference)
        assert practice != reference, f"{b['id']} behaves the same in both builds"
        assert json.loads(practice) == b["check"]["practice"], b["id"]
        assert json.loads(reference) == b["check"]["reference"], b["id"]
