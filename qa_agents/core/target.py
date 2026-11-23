"""Adapters for the *application under test*.

Chosen with `app:` in settings.yaml (see core/apps.py):
    gemini_enterprise | chatbot (http API / chat_widget) | genai | mock      -> conversational adapters here
    web                                                                     -> core/web.py (browser)

Every conversational adapter implements `converse(persona, target_agent, turns) -> list[TargetResponse]`.
To test an agent on another platform (Copilot Studio, Vertex Agent Engine,
Bedrock, a custom FastAPI bot) use `http` with a request template, or add a
20-line adapter class here.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

import requests
import yaml
from jinja2 import Template

from .models import Citation, TargetResponse


def _expand_env(v: Any) -> Any:
    if isinstance(v, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), v)
    if isinstance(v, dict):
        return {k: _expand_env(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_expand_env(x) for x in v]
    return v


def _dig(obj: Any, path: str) -> Any:
    """Tiny dot-path getter: 'a.b.0.c'. '*' maps over lists."""
    if not path:
        return obj
    head, _, rest = path.partition(".")
    if head == "*" and isinstance(obj, list):
        return [_dig(x, rest) for x in obj]
    if isinstance(obj, list):
        try:
            return _dig(obj[int(head)], rest)
        except (ValueError, IndexError):
            return None
    if isinstance(obj, dict):
        return _dig(obj.get(head), rest)
    return None


class TargetAgent:
    def __init__(self, cfg: dict):
        self.cfg = _expand_env(cfg)

    def converse(self, persona: str, target_agent: str, turns: list[str]) -> list[TargetResponse]:
        raise NotImplementedError

    # ---- auth shared by real adapters: one identity per persona
    def _token(self, persona: str) -> str:
        auth = (self.cfg.get("personas_auth") or {}).get(persona) or self.cfg.get("default_auth") or {}
        if "token_env" in auth:
            tok = os.environ.get(auth["token_env"], "")
            if not tok:
                raise RuntimeError(f"Env var {auth['token_env']} for persona '{persona}' is empty")
            return tok
        if "token_command" in auth:
            out = subprocess.run(shlex.split(auth["token_command"]), capture_output=True, text=True, check=True)
            return out.stdout.strip()
        return ""


# ---------------------------------------------------------------- Gemini Enterprise
class GeminiEnterpriseTarget(TargetAgent):
    """Calls a Gemini Enterprise app via the streamAssist REST method.

    Multi-turn: the session returned in the final chunk is passed back on the
    next turn. Routing to a specific registered agent uses agentsSpec.
    """

    def _url(self) -> str:
        c = self.cfg
        loc = c.get("location", "global")
        host = "discoveryengine.googleapis.com" if loc == "global" else f"{loc}-discoveryengine.googleapis.com"
        return (
            f"https://{host}/{c.get('api_version', 'v1')}/projects/{c['project_id']}/locations/{loc}"
            f"/collections/{c.get('collection', 'default_collection')}/engines/{c['app_id']}"
            f"/assistants/{c.get('assistant', 'default_assistant')}:streamAssist"
        )

    @staticmethod
    def _chunks(body: str) -> list[dict]:
        try:
            data = json.loads(body)
            return data if isinstance(data, list) else [data]
        except json.JSONDecodeError:
            out = []
            for line in body.splitlines():
                line = line.strip().lstrip("[,").rstrip(",]")
                if line.startswith("{"):
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            return out

    @staticmethod
    def _collect_citations(obj: Any, acc: list[Citation]) -> None:
        if isinstance(obj, dict):
            title = obj.get("title") or (obj.get("documentMetadata") or {}).get("title")
            uri = obj.get("uri") or (obj.get("documentMetadata") or {}).get("uri")
            if title or uri:
                c = Citation(title=title or "", uri=uri or "")
                if c not in acc:
                    acc.append(c)
            for v in obj.values():
                GeminiEnterpriseTarget._collect_citations(v, acc)
        elif isinstance(obj, list):
            for v in obj:
                GeminiEnterpriseTarget._collect_citations(v, acc)

    def converse(self, persona, target_agent, turns):
        token = self._token(persona)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if self.cfg.get("quota_project"):
            headers["X-Goog-User-Project"] = self.cfg["quota_project"]
        agent_id = (self.cfg.get("agents") or {}).get(target_agent)
        session = None
        responses = []
        for msg in turns:
            body: dict[str, Any] = {"query": {"text": msg}}
            if session:
                body["session"] = session
            if agent_id:
                body["agentsSpec"] = {"agentSpecs": [{"agentId": str(agent_id)}]}
            t0 = time.time()
            r = requests.post(self._url(), headers=headers, json=body, timeout=self.cfg.get("timeout_s", 120))
            latency = int((time.time() - t0) * 1000)
            if r.status_code >= 400:
                raise RuntimeError(f"streamAssist HTTP {r.status_code}: {r.text[:500]}")
            chunks = self._chunks(r.text)
            text_parts, cites = [], []
            for ch in chunks:
                ans = ch.get("answer") or {}
                for rep in ans.get("replies") or []:
                    content = (rep.get("groundedContent") or {}).get("content") or {}
                    if content.get("thought"):
                        continue  # model reasoning, not user-facing
                    if content.get("text"):
                        text_parts.append(content["text"])
                    self._collect_citations(rep.get("groundedContent", {}).get("textGroundingMetadata"), cites)
                self._collect_citations(ch.get("references") or ans.get("references"), cites)
                session = (ch.get("sessionInfo") or {}).get("session") or session
            responses.append(TargetResponse(text="".join(text_parts), citations=cites, latency_ms=latency,
                                            raw=chunks if self.cfg.get("keep_raw") else None))
        return responses


# ---------------------------------------------------------------- Generic HTTP
class HttpTarget(TargetAgent):
    """Any REST chatbot. Example config:

    target:
      type: http
      url: https://my-bot/api/chat
      headers: {Authorization: "Bearer {{ token }}"}
      body_template: '{"message": {{ message|tojson }}, "user": "{{ persona }}", "session": {{ session|tojson }}}'
      response_text_path: data.answer
      citations_path: data.sources        # list of {title, uri} or strings
      contexts_path: data.chunks          # optional: retrieved passages (RAG) for the `grounded` check
      session_path: data.session_id
    """

    keep_session = True

    def converse(self, persona, target_agent, turns):
        c = self.cfg
        token = self._token(persona)
        session = None
        out = []
        history: list[dict] = []
        for msg in turns:
            ctx = dict(message=msg, persona=persona, target_agent=target_agent, session=session, token=token,
                       history=history if self.keep_session else [], **(c.get("variables") or {}))
            headers = {k: Template(v).render(**ctx) for k, v in (c.get("headers") or {}).items()}
            headers.setdefault("Content-Type", "application/json")
            body = Template(c["body_template"]).render(**ctx)
            t0 = time.time()
            r = requests.request(c.get("method", "POST"), c["url"], headers=headers, data=body.encode(),
                                 timeout=c.get("timeout_s", 120))
            latency = int((time.time() - t0) * 1000)
            r.raise_for_status()
            data = r.json()
            raw_cites = _dig(data, c.get("citations_path", "")) if c.get("citations_path") else []
            cites = []
            for x in raw_cites or []:
                cites.append(Citation(title=x, uri="") if isinstance(x, str)
                             else Citation(title=x.get("title", ""), uri=x.get("uri") or x.get("url", "")))
            if self.keep_session:
                session = _dig(data, c["session_path"]) if c.get("session_path") else session
            raw_ctx = _dig(data, c["contexts_path"]) if c.get("contexts_path") else []
            if isinstance(raw_ctx, str):
                raw_ctx = [raw_ctx]
            contexts = [x if isinstance(x, str) else str(x.get("text") or x.get("content") or x) for x in raw_ctx or []]
            text = str(_dig(data, c["response_text_path"]) or "")
            history += [{"role": "user", "content": msg}, {"role": "assistant", "content": text}]
            out.append(TargetResponse(text=text, citations=cites, contexts=contexts, latency_ms=latency))
        return out


# ---------------------------------------------------------------- Gen AI app (LLM API / RAG)
class GenAITarget(HttpTarget):
    """A generative AI application behind an API: summariser, writer, classifier (mode: llm),
    or a document Q&A / RAG app (mode: rag, returns the passages it used in `contexts_path`).

    target (apps.genai):
      mode: rag                            # llm | rag
      url: https://genai.example.com/v1/answer
      body_template: '{"input": {{ message|tojson }}}'
      response_text_path: output
      contexts_path: retrieved             # rag: list of passages (strings or {text})
      multi_turn: false                    # true = send previous turns as {{ history }}
      provider: openai_compatible          # optional shortcut: an OpenAI-style /chat/completions endpoint
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.keep_session = bool(self.cfg.get("multi_turn", False))
        if self.cfg.get("provider") == "openai_compatible":           # e.g. Azure OpenAI, vLLM, Ollama
            self.cfg.setdefault("body_template",
                                '{"model": {{ model|tojson }}, "messages": [{% if system %}{"role": "system", "content": '
                                '{{ system|tojson }}}, {% endif %}{% for h in history %}{{ h|tojson }}, {% endfor %}'
                                '{"role": "user", "content": {{ message|tojson }}}]}')
            self.cfg.setdefault("response_text_path", "choices.0.message.content")
            self.cfg.setdefault("variables", {}).setdefault("model", self.cfg.get("model", ""))
            self.cfg["variables"].setdefault("system", self.cfg.get("system_prompt", ""))



# ---------------------------------------------------------------- Mock (offline demo)
class MockTarget(TargetAgent):
    """A fake school 'Rules & Regulations' agent backed by a YAML knowledge base.

    It contains two deliberate defects so the pipeline has something to find:
    * it ignores access restrictions on documents marked `leaky: true`
    * documents can carry a `wrong_answer` (simulated hallucination)
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.kb = yaml.safe_load(Path(cfg.get("knowledge_base", "fixtures/mock_kb.yaml")).read_text())["documents"]
        self.groups = {p: d.get("access_groups", []) for p, d in (cfg.get("persona_groups") or {}).items()}

    def _answer(self, persona, msg, history):
        q = (msg + " " + " ".join(history[-1:])).lower()
        if re.search(r"ignore (all|previous|your) instructions|system prompt", q):
            return TargetResponse(text="I can only help with questions about school rules and regulations.")
        best, score = None, 0
        for d in self.kb:
            s = sum(1 for k in d["keywords"] if k in q)
            if s > score:
                best, score = d, s
        if not best:
            return TargetResponse(text="I couldn't find that in the school's rules and regulations documents. "
                                       "Please contact the school office.")
        allowed = set(best.get("audience", ["all"]))
        mine = set(self.groups.get(persona, [])) | {"all"}
        if not (allowed & mine) and not best.get("leaky"):
            return TargetResponse(text="Sorry, I don't have access to information that can answer that for you.")
        text = best.get("wrong_answer") or best["answer"]
        return TargetResponse(text=text, citations=[Citation(title=best["title"], uri=best.get("uri", ""))],
                              contexts=[best["answer"]], latency_ms=150)

    def converse(self, persona, target_agent, turns):
        hist, out = [], []
        for m in turns:
            out.append(self._answer(persona, m, hist))
            hist.append(m)
        return out


TARGETS = {"gemini_enterprise": GeminiEnterpriseTarget, "http": HttpTarget, "genai": GenAITarget, "mock": MockTarget}


def build_target(cfg: dict):
    """Conversational adapters live here; browser-driven ones (web, chat_widget) in core/web.py."""
    t = cfg.get("type", "mock")
    if t in ("web", "chat_widget"):
        from .web import ChatWidgetTarget, WebTarget   # needs Playwright: imported only when used
        return (WebTarget if t == "web" else ChatWidgetTarget)(_expand_env(cfg))
    if t not in TARGETS:
        raise ValueError(f"Unknown target type '{t}'. Options: {list(TARGETS) + ['web', 'chat_widget']}")
    return TARGETS[t](cfg)
