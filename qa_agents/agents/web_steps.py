"""Turn plain-language manual test steps into browser actions, without AI.

Understands the way testers usually write steps. Values in quotes are safest:
    Open the Student login page                      -> goto  "Student login"
    Sign in as student                               -> login student
    Enter '1KV21CS001' in the USN field              -> fill  USN = 1KV21CS001
    Enter the Copies as 11 / Type 11 into Copies     -> fill  Copies = 11
    Select 'Anti-Ragging' in Category                -> select Category = Anti-Ragging
    Choose 'International Courier'                   -> check  International Courier   (radio button)
    Tick 'Remember this device'                      -> check
    Click 'Send OTP' / Press the Pay button          -> click
    Upload 'generate:big.pdf:5.3MB' to Government ID -> upload
    Press Enter                                      -> press Enter
    Wait 2 seconds                                   -> wait 2000
    Verify the page shows 'Request submitted'        -> expect_text
    Check that 'Payment failed' is not shown         -> expect_no_text
Steps it cannot read are returned in `unparsed`; the AI (or a human) handles those.
"""
from __future__ import annotations

import re

from ..core.models import WebAction, WebActionType as A

Q = r"""['"‘’“”]"""
QV = rf"{Q}(?P<v>[^'\"‘’“”]+){Q}"            # a quoted value
FIELD = r"(?:the\s+)?(?P<f>.+?)(?:\s+(?:field|box|input|textbox|text box|dropdown|drop-down|list|area))?"


def _clean(s: str) -> str:
    s = re.sub(r"^\s*(?:step\s*\d+\s*[:.)-]|\d+\s*[.)-])\s*", "", s.strip(), flags=re.I)
    return s.rstrip(" .;")


def _strip_q(s: str) -> str:
    return re.sub(rf"^{Q}|{Q}$", "", s.strip()).strip()


PATTERNS: list[tuple[re.Pattern, callable]] = []


def rule(rx: str):
    def deco(fn):
        PATTERNS.append((re.compile(rx, re.I), fn))
        return fn
    return deco


@rule(rf"^(?:sign|log)\s*(?:in|on)\s+(?:to .+?\s+)?as\s+(?:an?\s+|the\s+)?(?P<v>.+?)(?:\s+\(.*\))?$")
def _login(m):
    return [WebAction(action=A.login, value=_strip_q(m["v"]))]


@rule(rf"^(?:open|go to|navigate to|visit|launch|browse to)\s+(?:the\s+)?(?P<v>.+?)(?:\s+(?:page|screen|url|link|tab))?$")
def _goto(m):
    return [WebAction(action=A.goto, target=_strip_q(m["v"]))]


@rule(rf"^(?:enter|type|fill(?: in)?|input|key in|write)\s+{QV}\s+(?:in|into|in to|as|for|on)\s+{FIELD}$")
def _fill_q_first(m):
    return [WebAction(action=A.fill, target=_strip_q(m["f"]), value=m["v"])]


@rule(rf"^(?:enter|type|fill(?: in)?|input|set)\s+{FIELD}\s+(?:as|=|to|with|:)\s*{QV}$")
def _fill_f_first_q(m):
    return [WebAction(action=A.fill, target=_strip_q(m["f"]), value=m["v"])]


@rule(r"^(?:enter|type|fill(?: in)?|input|set)\s+(?:the\s+)?(?P<f>.+?)\s+(?:as|=|to|with|:)\s*(?P<v>\S.*)$")
def _fill_f_first(m):
    return [WebAction(action=A.fill, target=_strip_q(m["f"]), value=_strip_q(m["v"]))]


@rule(r"^(?:enter|type|input)\s+(?:the\s+)?(?P<f>[A-Za-z][\w /()-]*?)\s+(?P<v>\S+)\s+(?:in|into)\s+(?:the\s+)?(?P=f)(?:\s+field)?$")
def _fill_doubled(m):            # "Enter the USN 1KV21CS001 in the USN field"
    return [WebAction(action=A.fill, target=m["f"].strip(), value=_strip_q(m["v"]))]


@rule(r"^(?:enter|type|input)\s+(?P<v>\S+)\s+(?:in|into)\s+(?:the\s+)?(?P<f>.+?)(?:\s+field)?$")
def _fill_bare(m):
    return [WebAction(action=A.fill, target=m["f"].strip(), value=_strip_q(m["v"]))]


@rule(rf"^(?:select|choose|pick)\s+{QV}\s+(?:in|from|for|as)\s+{FIELD}$")
def _select(m):
    return [WebAction(action=A.select, target=_strip_q(m["f"]), value=m["v"])]


@rule(rf"^(?:select|choose|pick|tick|check|mark)\s+(?:the\s+)?(?:option\s+)?{QV}(?:\s+(?:option|radio(?: button)?|checkbox|check box|box))?$")
def _choose(m):
    return [WebAction(action=A.check, target=m["v"])]


@rule(r"^(?:tick|check)\s+(?:the\s+)?(?P<v>.+?)\s+(?:checkbox|check box|box|option)$")
def _tick(m):
    return [WebAction(action=A.check, target=_strip_q(m["v"]))]


@rule(r"^(?:untick|uncheck|clear)\s+(?:the\s+)?(?P<v>.+?)(?:\s+(?:checkbox|check box|box|option))?$")
def _untick(m):
    return [WebAction(action=A.uncheck, target=_strip_q(m["v"]))]


@rule(rf"^(?:upload|attach|choose file)\s+{QV}\s+(?:in|into|to|as|for|under)\s+{FIELD}$")
def _upload(m):
    return [WebAction(action=A.upload, target=_strip_q(m["f"]), value=m["v"])]


@rule(r"^press\s+(?:the\s+)?(?P<v>enter|tab|escape|esc)(?:\s+key)?$")
def _press(m):
    return [WebAction(action=A.press, value={"esc": "Escape"}.get(m["v"].lower(), m["v"].capitalize()))]


@rule(r"^(?:click|press|tap|hit|select)\s+(?:on\s+)?(?:the\s+)?(?P<v>.+?)(?:\s+(?:button|link|tab|icon|menu|option))?$")
def _click(m):
    return [WebAction(action=A.click, target=_strip_q(m["v"]))]


@rule(r"^wait\s+(?:for\s+)?(?P<n>[\d.]+)\s*(?P<u>s|sec|secs|seconds?|ms|milliseconds?)$")
def _wait(m):
    n = float(m["n"]) * (1 if m["u"].lower().startswith("m") else 1000)
    return [WebAction(action=A.wait, value=str(int(n)))]


@rule(rf"^(?:verify|check|confirm|ensure|observe|see)\s+(?:that\s+)?(?:the\s+)?(?:page|screen|system|portal|message)?\s*"
      rf"(?:does not|doesn't|should not|must not|do not|is not|isn't)\s+(?:show|display|contain|list)\s*{QV}$")
def _no_text_a(m):
    return [WebAction(action=A.expect_no_text, value=m["v"])]


@rule(rf"^(?:verify|check|confirm|ensure)\s+(?:that\s+)?{QV}\s+(?:is not|isn't|does not|doesn't)\s+(?:shown|displayed|appear|visible|listed)$")
def _no_text_b(m):
    return [WebAction(action=A.expect_no_text, value=m["v"])]


@rule(rf"^(?:verify|check|confirm|ensure|observe|see)\s+(?:that\s+)?(?:the\s+)?(?:page|screen|system|portal|message|it)?\s*"
      rf"(?:shows|displays|contains|lists|says|reads|is showing|has)\s+(?:the\s+)?(?:\w+\s+)?{QV}$")
def _text_a(m):
    return [WebAction(action=A.expect_text, value=m["v"])]


@rule(rf"^(?:verify|check|confirm|ensure|observe|see)\s+(?:that\s+)?{QV}\s+(?:is|appears|gets)\s+(?:shown|displayed|visible|listed)$")
def _text_b(m):
    return [WebAction(action=A.expect_text, value=m["v"])]


@rule(rf"^(?:verify|check|confirm|ensure)\s+(?:that\s+)?(?:the\s+)?(?P<f>.+?)\s+(?:shows|holds|is|equals|has value)\s+{QV}$")
def _value(m):
    return [WebAction(action=A.expect_text, value=m["v"])]


def parse_step(step: str) -> list[WebAction] | None:
    s = _clean(step)
    if not s:
        return []
    for rx, fn in PATTERNS:
        m = rx.match(s)
        if m:
            return fn(m)
    return None


def parse_steps(steps: list[str]) -> tuple[list[WebAction], list[str]]:
    """Returns (actions, steps that could not be read)."""
    actions, unparsed = [], []
    for i, st in enumerate(steps, 1):
        acts = parse_step(st)
        if acts is None:
            unparsed.append(st)
            continue
        for a in acts:
            a.step = i
            actions.append(a)
    return actions, unparsed


def expectations_from(expected_result: str, criteria: list[str]) -> list[WebAction]:
    """Quoted text in the expected result becomes 'the page shows ...' checks at the end of the test.
    A quote counts as 'must NOT be shown' when its own clause says so ("... 'X' is not shown")."""
    neg = re.compile(r"\b(not|no longer|never|isn't|doesn't|without|hidden|disappears?)\b", re.I)
    out, seen = [], set()
    for text in [expected_result, *criteria]:
        quotes = list(re.finditer(rf"{Q}([^'\"‘’“”]{{2,120}}){Q}", text or ""))
        for i, m in enumerate(quotes):
            v = m.group(1).strip()
            if v.lower() in seen:
                continue
            seen.add(v.lower())
            stop = quotes[i + 1].start() if i + 1 < len(quotes) else len(text)
            after = re.split(r"[,;.]|\band\b|\bbut\b", text[m.end():stop], maxsplit=1)[0]
            before = re.split(r"[,;.]|\band\b|\bbut\b", text[max(0, m.start() - 40):m.start()])[-1]
            negative = bool(neg.search(after) or re.search(r"\b(no|not|never|without)\b[^'\"]*$", before, re.I))
            out.append(WebAction(action=A.expect_no_text if negative else A.expect_text, value=v, step=0))
    return out
