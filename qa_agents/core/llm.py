"""LLM provider abstraction.

The agents only ever call `LLMClient.complete_json(...)`. Swap providers in
config/settings.yaml without touching agent code:

    llm:
      provider: gemini | anthropic | openai | mock
      model: ...

`openai` also covers any OpenAI-compatible endpoint (Azure OpenAI, Ollama,
vLLM, LM Studio) via `base_url`.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> str:
    """Pull a JSON object/array out of a model reply (handles ``` fences and chatter)."""
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise LLMError(f"No JSON found in model output: {text[:300]}")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    return text[start : end + 1]


class LLMClient:
    name = "base"

    def __init__(self, model: str = "", temperature: float = 0.2, max_tokens: int = 8192, **kwargs):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.kwargs = kwargs

    # providers implement this
    def complete(self, system: str, user: str, role: str = "") -> str:  # pragma: no cover
        raise NotImplementedError

    def complete_json(self, system: str, user: str, schema: Type[T], role: str = "", retries: int = 2) -> T:
        schema_txt = json.dumps(schema.model_json_schema(), indent=1)
        sys_full = (
            f"{system}\n\nRespond with ONLY a single JSON object that validates against this JSON Schema. "
            f"No prose, no markdown.\n<json_schema>\n{schema_txt}\n</json_schema>"
        )
        prompt = user
        last_err = None
        for _ in range(retries + 1):
            raw = self.complete(sys_full, prompt, role=role)
            try:
                return schema.model_validate_json(extract_json(raw))
            except (ValidationError, LLMError, json.JSONDecodeError) as e:
                last_err = e
                prompt = (
                    f"{user}\n\nYour previous reply was invalid:\n{str(e)[:1500]}\n"
                    "Return corrected JSON only."
                )
        raise LLMError(f"[{role}] could not get valid {schema.__name__}: {last_err}")


# ------------------------------------------------------------------ providers
class GeminiClient(LLMClient):
    """Google Gemini via google-genai. Uses Vertex AI if `vertex: true` (ADC auth), else GEMINI_API_KEY."""

    name = "gemini"

    def __init__(self, **kw):
        super().__init__(**kw)
        from google import genai  # lazy import

        if self.kwargs.get("vertex"):
            self.client = genai.Client(
                vertexai=True,
                project=self.kwargs.get("project") or os.environ.get("GOOGLE_CLOUD_PROJECT"),
                location=self.kwargs.get("location", "us-central1"),
            )
        else:
            self.client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    def complete(self, system, user, role=""):
        from google.genai import types

        resp = self.client.models.generate_content(
            model=self.model or "gemini-2.5-pro",
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
                response_mime_type="application/json",
            ),
        )
        return resp.text


class AnthropicClient(LLMClient):
    name = "anthropic"

    def __init__(self, **kw):
        super().__init__(**kw)
        import anthropic

        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY

    def complete(self, system, user, role=""):
        msg = self.client.messages.create(
            model=self.model or "claude-sonnet-5-5",
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


class OpenAIClient(LLMClient):
    """OpenAI or any OpenAI-compatible server (Azure, Ollama, vLLM...)."""

    name = "openai"

    def __init__(self, **kw):
        super().__init__(**kw)
        from openai import OpenAI

        self.client = OpenAI(base_url=self.kwargs.get("base_url"), api_key=os.environ.get("OPENAI_API_KEY", "none"))

    def complete(self, system, user, role=""):
        r = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return r.choices[0].message.content


class MockLLM(LLMClient):
    """Offline provider for demos / CI smoke tests: returns fixtures/mock_llm/<role>.json."""

    name = "mock"

    def __init__(self, fixtures_dir: str = "fixtures/mock_llm", **kw):
        super().__init__(**kw)
        self.dir = Path(fixtures_dir)

    def complete(self, system, user, role=""):
        f = self.dir / f"{role}.json"
        if not f.exists():
            raise LLMError(f"MockLLM has no fixture for role '{role}' ({f})")
        return f.read_text(encoding="utf-8")


PROVIDERS = {"gemini": GeminiClient, "anthropic": AnthropicClient, "openai": OpenAIClient, "mock": MockLLM}


def build_llm(cfg: dict) -> LLMClient:
    cfg = dict(cfg)
    provider = cfg.pop("provider", "mock")
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider '{provider}'. Options: {list(PROVIDERS)}")
    return PROVIDERS[provider](**cfg)
