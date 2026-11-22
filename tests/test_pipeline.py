import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

from qa_agents.agents.automation_engineer import AutomationEngineer  # noqa: E402
from qa_agents.core.evaluator import Evaluator  # noqa: E402
from qa_agents.core.llm import extract_json  # noqa: E402
from qa_agents.core.models import (Assertion, AssertionType, Citation, ExecutableTest, TargetResponse,  # noqa: E402
                                   TestCase)
from qa_agents.core.target import GeminiEnterpriseTarget  # noqa: E402
from qa_agents.orchestrator import Pipeline, load_usecase  # noqa: E402


def test_extract_json_handles_fences_and_chatter():
    assert json.loads(extract_json('Sure!\n```json\n{"a": 1}\n```\nthanks')) == {"a": 1}
    assert json.loads(extract_json('here: {"a": [1,2]} done')) == {"a": [1, 2]}


@pytest.mark.parametrize("atype,value,text,expected", [
    (AssertionType.contains_all, ["9:00", "pm"], "Curfew is 9:00 PM", True),
    (AssertionType.contains_all, ["10:00"], "Curfew is 9:00 PM", False),
    (AssertionType.contains_any, ["21:00", "9 pm"], "back by 9 PM", True),
    (AssertionType.not_contains, ["vice principal"], "Sorry, I can't share that", True),
    (AssertionType.not_contains, ["vice principal"], "The Vice Principal decides", False),
    (AssertionType.refusal, None, "Sorry, I don't have access to information that can answer that.", True),
    (AssertionType.refusal, None, "The committee has 4 members.", False),
    (AssertionType.regex, r"\b\d{1,2}%", "minimum 75% attendance", True),
])
def test_deterministic_assertions(atype, value, text, expected):
    r = Evaluator(None).check(Assertion(type=atype, value=value), [TargetResponse(text=text)])
    assert r.passed is expected, r.detail


def test_cites_source_and_turn_index():
    resps = [TargetResponse(text="a"), TargetResponse(text="b", citations=[Citation(title="Hostel_Rules_2026.pdf")])]
    ev = Evaluator(None)
    assert ev.check(Assertion(type=AssertionType.cites_source, value="hostel_rules", turn=1), resps).passed
    assert not ev.check(Assertion(type=AssertionType.cites_source, value="hostel_rules", turn=0), resps).passed


def _tc(category, expected, criteria):
    return TestCase(id="T1", usecase_id="U", title="t", category=category, priority="P1", persona="student",
                    steps=["q"], expected_result=expected, acceptance_criteria=criteria)


def test_harden_adds_refusal_only_for_denial_tests():
    deny = _tc("access_control", "Declines and reveals nothing", ["Declines"])
    allow = _tc("access_control", "Answers from Staff_Handbook", ["Mentions members"])
    base = ExecutableTest(test_id="T1", persona="x", target_agent="y", turns=["changed"],
                          assertions=[Assertion(type=AssertionType.contains_any, value=["a"])])
    h1 = AutomationEngineer._harden(base.model_copy(deep=True), deny, "rules")
    h2 = AutomationEngineer._harden(base.model_copy(deep=True), allow, "rules")
    assert AssertionType.refusal in {a.type for a in h1.assertions}
    assert AssertionType.refusal not in {a.type for a in h2.assertions}
    assert h1.turns == ["q"] and h1.persona == "student"  # never drifts from manual test case


def test_gemini_enterprise_stream_parsing():
    body = json.dumps([
        {"answer": {"state": "IN_PROGRESS", "replies": [{"groundedContent": {"content": {"text": "thinking...", "thought": True}}}]}},
        {"answer": {"replies": [{"groundedContent": {"content": {"text": "Curfew is "}}}]}},
        {"answer": {"state": "SUCCEEDED", "replies": [{"groundedContent": {
            "content": {"text": "9:00 PM."},
            "textGroundingMetadata": {"references": [{"documentMetadata": {"title": "Hostel_Rules", "uri": "https://sp/x.pdf"}}]}}}]},
         "sessionInfo": {"session": "projects/p/locations/global/collections/default_collection/engines/e/sessions/123"}},
    ])
    chunks = GeminiEnterpriseTarget._chunks(body)
    texts = [r["groundedContent"]["content"] for c in chunks for r in c["answer"].get("replies", [])]
    assert "".join(t["text"] for t in texts if not t.get("thought")) == "Curfew is 9:00 PM."
    cites = []
    GeminiEnterpriseTarget._collect_citations(chunks[2], cites)
    assert any(c.title == "Hostel_Rules" for c in cites)


def test_end_to_end_mock(tmp_path):
    pipe = Pipeline("config/settings.yaml", log=lambda *_: None)
    uc = load_usecase(Path("inputs/usecases/UC-001_rules_agent.md"))
    assert uc.id == "UC-001"
    s = pipe.run(tmp_path, uc)
    assert s["results"] == {"passed": 9, "failed": 3}
    triage = {a["test_id"]: a["classification"] for a in json.loads((tmp_path / "04_triage.json").read_text())}
    assert triage == {"TC-UC-001-005": "test_defect", "TC-UC-001-006": "product_bug", "TC-UC-001-001": "product_bug"}
    bugs = json.loads((tmp_path / "04_bugs.json").read_text())
    assert {b["severity"] for b in bugs} == {"Critical", "High"}
    leak = next(b for b in bugs if b["severity"] == "Critical")
    assert "Staff_Handbook_Confidential.pdf" in leak["citations_returned"]  # evidence comes from the run, not the LLM
    assert (tmp_path / "02_testcases.csv").read_text(encoding="utf-8-sig").startswith("Test Case ID,")
    # resume only C+D from the saved artifacts
    s2 = pipe.run(tmp_path, start="execute")
    assert s2["results"] == s["results"]
