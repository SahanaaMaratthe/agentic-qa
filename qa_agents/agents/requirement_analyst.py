from __future__ import annotations

from ..core.models import UseCase, UseCaseUnderstanding
from .base import BaseAgent


class RequirementAnalyst(BaseAgent):
    """Requirement Analyst: use case (any length) -> structured understanding."""

    role = "requirement_analyst"
    prompt_file = "requirement_analyst.md"

    def run(self, usecase: UseCase, reference_docs: str = "") -> UseCaseUnderstanding:
        user = f"## Use case {usecase.id}: {usecase.title}\n\n{usecase.text}\n"
        if reference_docs:
            user += f"\n## Supporting material (BRD extracts, document lists)\n{reference_docs}\n"
        out = self.llm.complete_json(self.system_prompt(), user, UseCaseUnderstanding, role=self.role)
        out.usecase_id = usecase.id
        return out
