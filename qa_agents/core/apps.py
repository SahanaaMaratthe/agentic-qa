"""Which application is under test.

settings.yaml:

    app: web                      # web | chatbot | gemini_enterprise | genai | mock | none
    apps:
      web:               {...}    # one block per application type; only the chosen one is used
      chatbot:           {...}
      ...

Override per run:  python -m qa_agents run ... --app chatbot      (or the dropdown on the web page)

Older settings files with only a `target:` block keep working: `target.type` is used as the app.
"""
from __future__ import annotations

APP_TYPES: dict[str, str] = {
    "web": "Website / web portal (browser automation)",
    "chatbot": "Chatbot (REST API or chat widget on a web page)",
    "gemini_enterprise": "Gemini Enterprise agent",
    "genai": "Gen AI app (LLM API or RAG)",
    "mock": "Demo chatbot (offline, built in)",
    "none": "Design only (test cases, no execution)",
}

# What the Test Designer is told it is testing (also switches how steps are written).
SYSTEM_KIND = {
    "web": "a web application used through screens and forms (no chatbot)",
    "chatbot": "a conversational AI agent (chatbot / assistant)",
    "gemini_enterprise": "a conversational AI agent (chatbot / assistant)",
    "mock": "a conversational AI agent (chatbot / assistant)",
    "genai": "a conversational AI agent (chatbot / assistant): a generative AI application (LLM or RAG) "
             "that takes a user input and returns AI-generated text",
    "none": "an application or portal used through screens and forms (no chatbot)",
}

AI_APPS = {"chatbot", "gemini_enterprise", "genai", "mock"}


def resolve_app(settings: dict, override: str | None = None) -> dict:
    """Return the target config for this run: the chosen app block plus `app` and `type` keys.

    `type` is the adapter in core/target.py; `app` is the user-facing application type.
    """
    app = (override or settings.get("app") or "").strip()
    if not app:                                   # legacy settings: target: {type: ...}
        t = dict(settings.get("target") or {"type": "mock"})
        t["app"] = {"http": "chatbot"}.get(t.get("type", "mock"), t.get("type", "mock"))
        return t
    if app not in APP_TYPES:
        raise ValueError(f"Unknown app '{app}'. Choose one of: {', '.join(APP_TYPES)}")
    block = dict((settings.get("apps") or {}).get(app) or {})
    if not block and app == "mock" and settings.get("target"):
        block = dict(settings["target"])          # reuse the old mock block
    block["app"] = app
    if app == "chatbot":
        block["type"] = "chat_widget" if block.get("mode", "api") == "widget" else "http"
    else:
        block["type"] = app
    return block


def app_kind(target_cfg: dict) -> str:
    """web | conversational | none: decides how tests are automated and executed."""
    app = target_cfg.get("app") or target_cfg.get("type", "mock")
    if app == "none":
        return "none"
    if app == "web":
        return "web"
    return "conversational"


def is_ai_app(target_cfg: dict) -> bool:
    return (target_cfg.get("app") or target_cfg.get("type")) in AI_APPS or target_cfg.get("type") == "http"
