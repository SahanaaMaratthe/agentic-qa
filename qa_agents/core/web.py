"""Browser-driven targets (Playwright): web portals and chatbots that only exist as a chat widget.

    app: web
    apps:
      web:
        base_url: http://localhost:8600/index.html
        page_map: config/pagemaps/kvtu_practice.yaml    # optional: page names, field selectors, persona logins
        headless: false          # false = watch the browser; true = hidden (CI, nightly)
        slow_mo_ms: 250          # pause between actions so you can follow along (headed runs)
        screenshots: every_step  # every_step | on_failure | never
        timeout_ms: 8000
        ai_locator: true         # if a field can't be found by its name, ask the AI to pick it from the live page
        browser: chromium        # chromium | chrome | msedge (installed Chrome / Edge)

How a field named in a test step ("USN", "Send OTP") is found, in order:
  1. a CSS selector written as css=...
  2. the page map (config/pagemaps/*.yaml): exact selectors a developer or tester recorded
  3. the live page, the way a manual tester looks: label, button/link text, placeholder, name/id
  4. the AI: the page's fields and buttons are listed and the AI picks the one meant (needs a real model)
Fields found by 3 or 4 are written to learned_page_map.yaml in the run folder; copy them into the page map
to make later runs faster and more stable.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Template
from pydantic import BaseModel

from .models import ExecutableTest, StepLog, TargetResponse, WebAction, WebActionType

SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as e:  # pragma: no cover - depends on the machine
        raise RuntimeError("Browser testing needs Playwright. Install it once with:\n"
                           "    pip install playwright\n    playwright install chromium") from e


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def load_page_map(path_or_dict: Any) -> dict:
    if not path_or_dict:
        return {}
    if isinstance(path_or_dict, dict):
        return path_or_dict
    p = Path(path_or_dict)
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {} if p.exists() else {}


class PickedElement(BaseModel):
    index: int
    reason: str = ""


SCAN_JS = """() => {
  const els = [...document.querySelectorAll('input,select,textarea,button,a,[role=button],[role=link],[role=tab],summary,label')]
    .filter(e => { const r = e.getBoundingClientRect(); return (r.width > 0 && r.height > 0) || e.type === 'file'; });
  return els.slice(0, 250).map((e, i) => {
    e.setAttribute('data-qa-idx', String(i));
    const lab = e.id ? document.querySelector(`label[for="${CSS.escape(e.id)}"]`) : null;
    return { i, tag: e.tagName.toLowerCase(), type: e.type || '', id: e.id || '', name: e.name || '',
             label: (lab ? lab.innerText : '') || e.getAttribute('aria-label') || '',
             placeholder: e.placeholder || '', text: (e.innerText || e.value || '').trim().slice(0, 60) };
  });
}"""


class Browser:
    """One Playwright browser for a whole run; a fresh context (cookies, storage) per test."""

    def __init__(self, cfg: dict):
        _require_playwright()
        self.cfg = cfg
        self._pw = self._browser = None

    def start(self):
        if self._browser:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        kind = self.cfg.get("browser", "chromium")
        opts: dict = {"headless": bool(self.cfg.get("headless", True)), "slow_mo": int(self.cfg.get("slow_mo_ms", 0))}
        if self.cfg.get("executable_path"):
            opts["executable_path"] = self.cfg["executable_path"]
        elif kind in ("chrome", "msedge"):
            opts["channel"] = kind
        if self.cfg.get("browser_args"):
            opts["args"] = list(self.cfg["browser_args"])
        try:
            self._browser = self._pw.chromium.launch(**opts)
        except Exception as e:
            self._pw.stop()
            self._pw = None
            if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
                raise RuntimeError("The test browser is not installed. Run once:  playwright install chromium\n"
                                   "(or set browser: chrome / msedge under apps: web: to use your installed browser)") from e
            raise

    def new_page(self):
        self.start()
        vp = self.cfg.get("viewport") or {"width": 1280, "height": 860}
        ctx = self._browser.new_context(viewport=vp, accept_downloads=True)
        page = ctx.new_page()
        page.set_default_timeout(int(self.cfg.get("timeout_ms", 8000)))
        return ctx, page

    def stop(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        finally:
            self._browser = self._pw = None


class WebTarget:
    """Runs ExecutableTest.actions in a real browser and returns step-by-step evidence."""

    parallel_safe = False   # Playwright's sync API runs in one thread: tests run one after another

    def __init__(self, cfg: dict, llm=None):
        self.cfg = cfg
        self.map = load_page_map(cfg.get("page_map"))
        self.base_url = cfg.get("base_url") or self.map.get("base_url", "")
        self.llm = llm                       # set by the Automation Engineer for the AI locator
        self.learned: dict[str, str] = {}
        self.browser = Browser(cfg)
        self.shots = cfg.get("screenshots", "every_step")

    # ------------------------------------------------------------ public
    def close(self):
        self.browser.stop()

    def persona_login(self, persona: str) -> str | None:
        """Name of the page-map login recipe for this persona (matches id or aliases), else None."""
        p = _norm(persona).replace("_", " ")
        best, best_len = None, 0
        for name, spec in (self.map.get("personas") or {}).items():
            for a in [_norm(name).replace("_", " ")] + [_norm(x) for x in (spec or {}).get("aliases", [])]:
                if not a:
                    continue
                score = 1000 if a == p else (len(a) if re.search(rf"\b{re.escape(a)}\b", p) else 0)
                if score > best_len:
                    best, best_len = name, score
        return best

    def run_test(self, test: ExecutableTest, evidence_dir: Path) -> tuple[list[StepLog], TargetResponse, str]:
        """Returns (step logs, final page as a response, error message or '')."""
        out_dir = evidence_dir / SAFE.sub("_", test.test_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        vars_: dict[str, Any] = dict(self.map.get("variables") or {}) | dict(self.cfg.get("variables") or {})
        logs: list[StepLog] = []
        ctx, page = self.browser.new_page()
        dialogs: list[str] = []
        page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        error = ""
        try:
            for act in self._expand(self.map.get("setup") or []) + list(test.actions):
                log = self._do(page, act, vars_, out_dir, len(logs) + 1)
                if dialogs:
                    log.detail = (log.detail + f" | browser dialog: {dialogs[-1]}").strip(" |")
                    dialogs.clear()
                logs.append(log)
                if log.status == "failed" and not act.optional:
                    break
        except Exception as e:  # noqa: BLE001 - a browser crash is reported, not raised
            error = f"{type(e).__name__}: {str(e).splitlines()[0][:300]}"
        final = TargetResponse(text="", url="")
        try:
            final = TargetResponse(text=page.locator("body").inner_text(timeout=3000)[:20000], url=page.url)
            if self.shots != "never" and (self.shots == "every_step" or any(x.status == "failed" for x in logs) or error):
                shot = out_dir / "final.png"
                page.screenshot(path=str(shot), full_page=True)
                logs.append(StepLog(step=0, action="final page", status="passed", screenshot=str(shot), url=page.url))
        except Exception:  # noqa: BLE001
            pass
        ctx.close()
        return logs, final, error

    # ------------------------------------------------------------ actions
    def _expand(self, raw: list) -> list[WebAction]:
        return [a if isinstance(a, WebAction) else WebAction.model_validate(a) for a in raw]

    def _render(self, s: str, vars_: dict) -> str:
        return Template(s).render(**vars_) if "{{" in (s or "") else (s or "")

    def _url(self, target: str) -> str | None:
        """A page-map page name, URL or path -> full URL. None = a plain name the map doesn't know."""
        pages = self.map.get("pages") or {}
        key = re.sub(r"\s+(page|screen)$", "", _norm(target))
        hit = next((v for k, v in pages.items() if _norm(k) in (key, _norm(target))), None)
        path = (hit.get("url") if isinstance(hit, dict) else hit) if hit else target
        if not hit and not re.match(r"^(https?:|file:|#|/|\.|\w+\.html?)", path or "") and path:
            return None
        if re.match(r"^(https?|file):", path or ""):
            return path
        base = self.base_url
        if path.startswith("#"):
            return base.split("#")[0] + path
        if path.startswith("/") and re.match(r"^https?://[^/]+", base):
            return re.match(r"^https?://[^/]+", base).group(0) + path
        return base if not path else base.rstrip("/") + "/" + path.lstrip("/")

    def _do(self, page, a: WebAction, vars_: dict, out_dir: Path, n: int) -> StepLog:
        target, value = self._render(a.target, vars_), self._render(a.value, vars_)
        log = StepLog(step=a.step, action=a.action.value, target=target, value=value)
        t = a.action
        try:
            if t == WebActionType.login:
                recipe = self.persona_login(value or target)
                if not recipe:
                    raise LookupError(f"no login steps for persona '{value or target}' in the page map")
                for sub in self._expand(self.map["personas"][recipe].get("steps") or []):
                    sub_log = self._do(page, sub, vars_, out_dir, n)
                    if sub_log.status == "failed":
                        raise RuntimeError(f"login step '{sub.action.value} {sub.target}' failed: {sub_log.detail}")
                log.detail = f"signed in as {recipe}"
            elif t == WebActionType.goto:
                url = self._url(target or value)
                if url is None:                       # not in the page map: open the site, click the link like a tester
                    if not page.url.startswith(self.base_url.split("#")[0]) or page.url == "about:blank":
                        page.goto(self.base_url)
                    self._find(page, target or value, "clickable").click()
                    log.detail = f"'{target}' is not in the page map: clicked the link with that name"
                else:
                    page.goto(url)
                page.wait_for_load_state("domcontentloaded")
            elif t == WebActionType.fill:
                self._find(page, target, "field").fill(value)
            elif t == WebActionType.select:
                el = self._find(page, target, "field")
                try:
                    el.select_option(label=value)
                except Exception:  # noqa: BLE001
                    el.select_option(value=value)
            elif t in (WebActionType.check, WebActionType.uncheck):
                el = self._find(page, target or value, "choice")
                el.check() if t == WebActionType.check else el.uncheck()
            elif t == WebActionType.click:
                self._find(page, target or value, "clickable").click()
            elif t == WebActionType.upload:
                self._find(page, target, "file").set_input_files(self._file(value, out_dir))
            elif t == WebActionType.press:
                (self._find(page, target, "field") if target else page.keyboard).press(value or "Enter")
            elif t == WebActionType.wait:
                page.wait_for_timeout(int(float(value or 500)))
            elif t in (WebActionType.expect_text, WebActionType.expect_no_text):
                self._expect_text(page, target, value, present=t == WebActionType.expect_text)
            elif t == WebActionType.expect_url:
                deadline = time.time() + float(self.cfg.get("timeout_ms", 8000)) / 1000
                while value.lower() not in page.url.lower() and time.time() < deadline:
                    page.wait_for_timeout(150)
                if value.lower() not in page.url.lower():
                    raise AssertionError(f"URL is {page.url}, expected it to contain '{value}'")
            elif t == WebActionType.expect_value:
                got = self._find(page, target, "field").input_value()
                if _norm(got) != _norm(value):
                    raise AssertionError(f"'{target}' holds '{got}', expected '{value}'")
            elif t in (WebActionType.expect_visible, WebActionType.expect_hidden):
                el = self._find(page, target or value, "any", must_exist=t == WebActionType.expect_visible)
                visible = el is not None and el.is_visible()
                if visible != (t == WebActionType.expect_visible):
                    raise AssertionError(f"'{target or value}' is {'visible' if visible else 'not visible'}")
            elif t == WebActionType.run_js:
                res = page.evaluate(value)
                if a.save_as:
                    vars_[a.save_as] = res
                log.detail = f"{a.save_as or 'result'} = {str(res)[:80]}"
            elif t == WebActionType.screenshot:
                pass
            page.wait_for_timeout(int(self.cfg.get("settle_ms", 120)))
        except Exception as e:  # noqa: BLE001
            log.status = "failed"
            log.detail = (log.detail + " " + str(e).splitlines()[0][:400]).strip()
        log.url = page.url
        if self.shots == "every_step" or (self.shots == "on_failure" and log.status == "failed") \
                or t == WebActionType.screenshot:
            shot = out_dir / f"{n:02d}_{SAFE.sub('_', t.value)}_{SAFE.sub('_', target)[:30]}.png".replace("__", "_")
            try:
                page.screenshot(path=str(shot), full_page=log.status == "failed")
                log.screenshot = str(shot)
            except Exception:  # noqa: BLE001
                pass
        return log

    def _expect_text(self, page, target: str, value: str, present: bool):
        scope = self._find(page, target, "any") if target else page.locator("body")
        want = _norm(value)
        deadline = time.time() + float(self.cfg.get("timeout_ms", 8000)) / 1000 * (1 if present else 0.25)
        while True:
            have = _norm(scope.inner_text())
            if (want in have) == present:
                return
            if time.time() >= deadline:
                if present:
                    raise AssertionError(f"text '{value}' not found on the page")
                raise AssertionError(f"text '{value}' is shown but should not be")
            page.wait_for_timeout(150)

    @staticmethod
    def _file(value: str, out_dir: Path) -> str:
        """`generate:<name>:<size>` makes a test file on the fly, e.g. generate:big.pdf:5.3MB,
        generate:fake.pdf:text (a text file named .pdf). Anything else is a path to an existing file."""
        if not value.startswith("generate:"):
            p = Path(value)
            if not p.exists():
                raise FileNotFoundError(f"upload file not found: {value}")
            return str(p.resolve())
        _, name, *rest = value.split(":")
        spec = (rest[0] if rest else "10KB").strip().lower()
        f = out_dir / "files" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        if spec == "text":
            f.write_text("This is a plain text file pretending to be a PDF.\n")
            return str(f)
        m = re.match(r"([\d.]+)\s*(kb|mb)?", spec)
        size = int(float(m.group(1)) * (1024 * 1024 if (m.group(2) or "kb") == "mb" else 1024)) if m else 10240
        head = {".pdf": b"%PDF-1.4\n", ".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff\xe0",
                ".jpeg": b"\xff\xd8\xff\xe0"}.get(Path(name).suffix.lower(), b"")
        f.write_bytes(head + b"0" * max(0, size - len(head)))
        return str(f)

    # ------------------------------------------------------------ finding elements
    def _mapped(self, page, name: str) -> str | None:
        key = _norm(name)
        elements = dict(self.map.get("elements") or {})
        for pg in (self.map.get("pages") or {}).values():
            if isinstance(pg, dict):
                url = pg.get("url", "")
                if not url or url.split("?")[0] in page.url:
                    elements.update(pg.get("elements") or {})
        for k, sel in elements.items():
            if _norm(k) == key:
                return sel
        return self.learned.get(key)

    def _find(self, page, name: str, kind: str, must_exist: bool = True):
        if not name:
            raise LookupError("no field or button name given")
        if name.startswith(("css=", "xpath=", "text=", "#", "[")) and not re.match(r"^#/", name):
            loc = page.locator(name[4:] if name.startswith("css=") else name)
            if loc.count():
                return loc.first
        sel = self._mapped(page, name)
        if sel:
            loc = page.locator(sel)
            if loc.count():
                return loc.first
        loc = self._semantic(page, name, kind)
        if loc is not None:
            return loc
        loc = self._ai_pick(page, name, kind)
        if loc is not None:
            return loc
        if not must_exist:
            return None
        raise LookupError(f"could not find '{name}' on {page.url}")

    def _semantic(self, page, name: str, kind: str):
        rx = re.compile(re.escape(name.strip()), re.I)
        exact_rx = re.compile(rf"^\s*{re.escape(name.strip())}\s*$", re.I)
        tries = []
        if kind in ("field", "file", "choice", "any"):
            tries += [lambda: page.get_by_label(exact_rx), lambda: page.get_by_label(rx),
                      lambda: page.get_by_placeholder(rx)]
        if kind in ("clickable", "choice", "any"):
            tries += [lambda: page.get_by_role("button", name=exact_rx), lambda: page.get_by_role("link", name=exact_rx),
                      lambda: page.get_by_role("button", name=rx), lambda: page.get_by_role("link", name=rx),
                      lambda: page.get_by_role("tab", name=rx), lambda: page.get_by_label(rx)]
        if kind in ("clickable", "any"):
            tries += [lambda: page.get_by_text(exact_rx), lambda: page.get_by_text(rx)]
        slug = re.sub(r"[^a-z0-9]+", "", name.lower())
        tries.append(lambda: page.locator(f"[name='{slug}' i], [id='{slug}' i]"))
        for make in tries:
            try:
                loc = make()
                n = loc.count()
            except Exception:  # noqa: BLE001
                continue
            if n == 0:
                continue
            for i in range(min(n, 5)):
                cand = loc.nth(i)
                try:
                    if cand.is_visible() or kind == "file":
                        self._learn(page, name, cand)
                        return cand
                except Exception:  # noqa: BLE001
                    continue
        return None

    def _learn(self, page, name: str, loc) -> None:
        try:
            sel = loc.evaluate("e => e.id ? '#' + CSS.escape(e.id) : (e.name ? `[name=\"${e.name}\"]` : '')")
        except Exception:  # noqa: BLE001
            sel = ""
        if sel:
            self.learned[_norm(name)] = sel

    def _ai_pick(self, page, name: str, kind: str):
        if not self.cfg.get("ai_locator", True) or self.llm is None or getattr(self.llm, "name", "") == "mock":
            return None
        try:
            items = page.evaluate(SCAN_JS)
        except Exception:  # noqa: BLE001
            return None
        listing = "\n".join(f"{x['i']}: <{x['tag']} type={x['type']} id={x['id']} name={x['name']}> "
                            f"label='{x['label']}' placeholder='{x['placeholder']}' text='{x['text']}'" for x in items)
        try:
            pick = self.llm.complete_json(
                "You help a test robot use a web page. From the numbered list of elements on the current page, choose "
                "the one a human tester means by the given name. Return index -1 if none fits.",
                f"Looking for a {kind} called: {name}\nPage: {page.url}\n\nElements:\n{listing}", PickedElement,
                role="web_locator")
        except Exception:  # noqa: BLE001
            return None
        if pick.index < 0:
            return None
        loc = page.locator(f"[data-qa-idx='{pick.index}']")
        if loc.count():
            self._learn(page, name, loc.first)
            return loc.first
        return None

    def save_learned(self, run_dir: Path) -> Path | None:
        if not self.learned:
            return None
        f = run_dir / "learned_page_map.yaml"
        f.write_text("# Fields the robot found by reading the page. Copy into your page map under `elements:`\n"
                     + yaml.safe_dump({"elements": dict(sorted(self.learned.items()))}, allow_unicode=True,
                                      sort_keys=False), encoding="utf-8")
        return f


class ChatWidgetTarget:
    """A chatbot that is only reachable through a chat box on a web page.

    apps:
      chatbot:
        mode: widget
        url: https://portal.example.com/help
        open: "Chat with us"          # optional: button that opens the widget
        input: "css=#chat-input"      # the message box (name, label or css=)
        send: "Send"                  # optional: send button; default = press Enter
        bot_messages: "css=.msg.bot"  # every bot reply bubble
        reply_timeout_ms: 30000
        login: [...]                  # optional web actions to sign in first (same format as page-map steps)
    """

    parallel_safe = False

    def __init__(self, cfg: dict, llm=None):
        self.cfg = cfg
        self.web = WebTarget({**cfg, "base_url": cfg.get("url", ""), "screenshots": "never"}, llm)

    def close(self):
        self.web.close()

    def converse(self, persona, target_agent, turns):
        c = self.cfg
        ctx, page = self.web.browser.new_page()
        out = []
        try:
            page.goto(c["url"])
            for act in self.web._expand(c.get("login") or []):
                log = self.web._do(page, act, {}, Path("."), 0)
                if log.status == "failed":
                    raise RuntimeError(f"chat widget login failed at {act.action.value} {act.target}: {log.detail}")
            if c.get("open"):
                self.web._find(page, c["open"], "clickable").click()
            bubbles = page.locator(c["bot_messages"].removeprefix("css="))
            for msg in turns:
                before = bubbles.count()
                box = self.web._find(page, c["input"], "field")
                box.fill(msg)
                t0 = time.time()
                (self.web._find(page, c["send"], "clickable").click() if c.get("send") else box.press("Enter"))
                deadline = t0 + int(c.get("reply_timeout_ms", 30000)) / 1000
                while bubbles.count() <= before and time.time() < deadline:
                    page.wait_for_timeout(200)
                if bubbles.count() <= before:
                    raise TimeoutError("the chatbot did not reply in time")
                last, stable = "", 0
                while stable < 3 and time.time() < deadline:    # wait until a streamed reply stops changing
                    page.wait_for_timeout(300)
                    now = bubbles.last.inner_text()
                    stable, last = (stable + 1, now) if now == last else (0, now)
                out.append(TargetResponse(text=last.strip(), latency_ms=int((time.time() - t0) * 1000), url=page.url))
        finally:
            ctx.close()
        return out
