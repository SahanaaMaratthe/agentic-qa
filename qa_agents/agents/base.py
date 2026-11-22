from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Template

from ..core.llm import LLMClient

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


class BaseAgent:
    """An agent = a role prompt + a typed input/output contract + an LLM.

    Agents never talk to each other directly; the orchestrator passes typed
    artifacts between them. That keeps each one swappable and testable alone.
    """

    role: str = "base"
    prompt_file: str = ""

    def __init__(self, llm: LLMClient, context: dict | None = None):
        self.llm = llm
        self.context = context or {}

    def system_prompt(self, **extra) -> str:
        tpl = Template((PROMPTS / self.prompt_file).read_text(encoding="utf-8"))
        return tpl.render(**{**self.context, **extra})

    @staticmethod
    def dump(obj) -> str:
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump(mode="json")
        elif isinstance(obj, list):
            obj = [o.model_dump(mode="json") if hasattr(o, "model_dump") else o for o in obj]
        return json.dumps(obj, indent=1, ensure_ascii=False)
