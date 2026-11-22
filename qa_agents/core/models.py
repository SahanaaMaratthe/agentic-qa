"""Shared data contracts between agents.

Every agent reads and writes these schemas as JSON, so any stage can be
replaced (another framework, another language, a human) as long as it honours
the same contract.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------- inputs
class UseCase(BaseModel):
    id: str
    title: str = ""
    text: str = Field(description="Raw use-case text, however short")
    source: str = ""


class Persona(BaseModel):
    id: str
    name: str
    description: str = ""
    access_groups: list[str] = []


# ---------------------------------------------------------------- Requirement Analyst
class AccessRule(BaseModel):
    persona: str
    allowed: list[str] = Field(default_factory=list, description="Content/doc types this persona may get answers from")
    denied: list[str] = Field(default_factory=list, description="Content/doc types this persona must NOT get answers from")


class UseCaseUnderstanding(BaseModel):
    usecase_id: str
    summary: str
    target_agent: str = Field(description="Logical name of the agent under test, e.g. 'rules_regulations'")
    personas: list[str]
    user_intents: list[str] = Field(description="Kinds of questions users will ask")
    business_rules: list[str] = Field(description="Behaviours the agent must exhibit")
    knowledge_sources: list[str] = Field(description="Documents / repositories the agent answers from")
    access_rules: list[AccessRule] = []
    out_of_scope: list[str] = []
    implicit_requirements: list[str] = Field(default_factory=list, description="Requirements not written but expected for an enterprise RAG agent")
    assumptions: list[str] = []
    open_questions: list[str] = []
    risk_areas: list[str] = []


# ---------------------------------------------------------------- Test Designer
class TestCategory(str, Enum):
    __test__ = False  # not a pytest class
    functional = "functional"
    negative = "negative"
    access_control = "access_control"
    grounding = "grounding"          # hallucination / citation correctness
    out_of_scope = "out_of_scope"
    multi_turn = "multi_turn"
    robustness = "robustness"        # typos, paraphrase, language mix
    security = "security"            # prompt injection, data exfiltration


class Priority(str, Enum):
    critical = "Critical"
    high = "High"
    medium = "Medium"
    low = "Low"


PRIORITY_ORDER = {Priority.critical: 0, Priority.high: 1, Priority.medium: 2, Priority.low: 3}
_LEGACY_PRIORITY = {"p0": "Critical", "p1": "High", "p2": "Medium", "p3": "Low", "p4": "Low",
                    "blocker": "Critical", "highest": "Critical", "major": "High", "minor": "Low", "lowest": "Low"}


class Perspective(str, Enum):
    end_user = "End user"
    business = "Business"
    both = "Both"


class TestCase(BaseModel):
    __test__ = False  # not a pytest class
    id: str
    usecase_id: str
    title: str = Field(description="Plain-language name starting with a verb, e.g. 'Student sees the weekday hostel curfew'")
    purpose: str = Field(default="", description="One plain sentence: what we check and why it matters. No jargon.")
    perspective: Perspective = Field(default=Perspective.end_user,
                                     description="End user = what a real user experiences; Business = rules, money, "
                                                 "compliance, operations; Both")
    category: TestCategory
    priority: Priority = Field(description="Critical | High | Medium | Low, from the priority rules")
    priority_reason: str = Field(default="", description="One plain sentence justifying the priority (impact x likelihood)")
    business_impact: str = Field(default="", description="What the organisation loses if this fails: money, compliance, "
                                                         "data, reputation, workload, user trust")
    persona: str
    preconditions: list[str] = []
    steps: list[str] = Field(description="One action per step in plain language. For a conversational agent each "
                                         "step is exactly the message the user types.")
    expected_result: str = Field(description="What anyone would observably see if the system works")
    acceptance_criteria: list[str] = Field(description="Objectively checkable statements")
    traceability: list[str] = Field(default_factory=list, description="Which intent / business rule / access rule this covers")
    based_on_assumption: Optional[str] = Field(default=None, description="Set if this test depends on an assumption from the gap report")
    extra: dict[str, Any] = Field(default_factory=dict, description="Values for custom columns of the test-case skeleton")

    @field_validator("priority", mode="before")
    @classmethod
    def _legacy_priority(cls, v):
        if isinstance(v, str):
            key = v.strip().lower()
            if key in _LEGACY_PRIORITY:
                return _LEGACY_PRIORITY[key]
            return v.strip().capitalize()
        return v

    @field_validator("perspective", mode="before")
    @classmethod
    def _perspective(cls, v):
        if isinstance(v, str):
            k = v.strip().lower().replace("_", " ").replace("-", " ")
            return {"end user": "End user", "user": "End user", "enduser": "End user", "business": "Business",
                    "both": "Both", "end user + business": "Both"}.get(k, v)
        return v


class GapType(str, Enum):
    missing_information = "missing_information"
    ambiguity = "ambiguity"
    contradiction = "contradiction"
    untestable = "untestable"
    missing_test_data = "missing_test_data"


class Gap(BaseModel):
    id: str
    type: GapType
    description: str
    impact: str = Field(description="What could go wrong / what cannot be tested")
    question_for_ba: str
    assumed_resolution: str = Field(description="Assumption used to keep generating tests")


class TestDesign(BaseModel):
    __test__ = False  # not a pytest class
    usecase_id: str
    test_cases: list[TestCase]
    gaps: list[Gap] = []
    coverage_notes: str = ""


# ---------------------------------------------------------------- Automation Engineer
class AssertionType(str, Enum):
    contains_all = "contains_all"
    contains_any = "contains_any"
    not_contains = "not_contains"
    regex = "regex"
    refusal = "refusal"              # agent should decline / say it can't share
    cites_source = "cites_source"    # a citation title/uri contains value
    semantic = "semantic"            # LLM-as-judge against a criterion
    max_latency_ms = "max_latency_ms"


class Assertion(BaseModel):
    type: AssertionType
    value: Any = Field(description="list[str] for contains_*, str for regex/cites_source/semantic, int for latency, null for refusal")
    turn: int = Field(default=-1, description="Which response to check; -1 = last")
    description: str = ""
    critical: bool = True


class ExecutableTest(BaseModel):
    test_id: str
    persona: str
    target_agent: str
    turns: list[str]
    assertions: list[Assertion]


class ExecutableSuite(BaseModel):
    usecase_id: str
    tests: list[ExecutableTest]


# ---------------------------------------------------------------- run results
class Citation(BaseModel):
    title: str = ""
    uri: str = ""


class TargetResponse(BaseModel):
    text: str
    citations: list[Citation] = []
    latency_ms: int = 0
    raw: Any = None


class AssertionResult(BaseModel):
    assertion: Assertion
    passed: bool
    detail: str = ""


class TestResult(BaseModel):
    __test__ = False  # not a pytest class
    test_id: str
    status: str  # passed | failed | error
    persona: str
    turns: list[str]
    responses: list[TargetResponse] = []
    assertion_results: list[AssertionResult] = []
    error: str = ""
    duration_ms: int = 0


# ---------------------------------------------------------------- Defect Manager
class BugClassification(str, Enum):
    product_bug = "product_bug"
    test_defect = "test_defect"        # the test/expectation is wrong
    environment = "environment"        # auth, network, quota
    needs_review = "needs_review"      # unclear, human must decide


class FailureAnalysis(BaseModel):
    test_id: str
    classification: BugClassification
    title: str
    severity: str = Field(description="Critical | High | Medium | Low")
    suspected_root_cause: str = Field(description="e.g. retrieval miss, wrong document, hallucination, access-control leak, over-refusal, routing")
    summary: str
    recommendation: str = ""


class FailureAnalysisBatch(BaseModel):
    analyses: list[FailureAnalysis]


class BugReport(BaseModel):
    id: str
    title: str
    severity: str
    classification: BugClassification
    suspected_root_cause: str
    usecase_id: str
    test_ids: list[str]
    persona: str
    steps_to_reproduce: list[str]
    expected: str
    actual: str
    failed_checks: list[str]
    citations_returned: list[str] = []
    summary: str = ""
    recommendation: str = ""
    labels: list[str] = []
    tracker_key: Optional[str] = None
