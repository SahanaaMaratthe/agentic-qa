"""Test Designer: priority from Critical to Low, end-user + business viewpoints, readable by everyone."""
import csv
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

from qa_agents.agents.design_quality import check_design, sort_and_renumber  # noqa: E402
from qa_agents.agents.test_designer import TestDesigner  # noqa: E402
from qa_agents.core.llm import LLMClient  # noqa: E402
from qa_agents.core.models import Priority, TestCase, TestDesign, UseCaseUnderstanding  # noqa: E402

GLOSSARY = {"OTP": "One-Time Password", "USN": "University Seat Number", "SLA": "Service Level Agreement"}
COMMON = ["PDF", "SMS", "ID"]


def tc(i, **kw):
    base = dict(id=f"T{i}", usecase_id="UC", title="Student sees the curfew", purpose="Checks the curfew time.",
                perspective="End user", category="functional", priority="High",
                priority_reason="Wrong time misleads students.", business_impact="Disciplinary disputes.",
                persona="student", steps=["Ask for the curfew"], expected_result="Shows 9:00 PM and the source.",
                acceptance_criteria=["States 9:00 PM"])
    base.update(kw)
    return TestCase(**base)


def rules(issues):
    return {(i.test_id, i.rule) for i in issues}


def test_legacy_priorities_and_perspective_spellings_are_accepted():
    assert tc(1, priority="P1").priority == Priority.high
    assert tc(1, priority="p0").priority == Priority.critical
    assert tc(1, priority="P3").priority == Priority.low
    assert tc(1, perspective="business").perspective.value == "Business"
    assert tc(1, perspective="end_user").perspective.value == "End user"


def test_clean_test_case_has_no_issues():
    assert check_design(TestDesign(usecase_id="UC", test_cases=[tc(1)]), GLOSSARY, COMMON) == []


def test_vague_expected_result_and_jargon_are_flagged():
    d = TestDesign(usecase_id="UC", test_cases=[
        tc(1, expected_result="The system works correctly."),
        tc(2, purpose="Check the API returns a JSON payload."),
    ])
    r = rules(check_design(d, GLOSSARY, COMMON))
    assert ("T1", "vague_expected") in r and ("T2", "jargon") in r


def test_abbreviations_must_be_spelled_out_once():
    d = TestDesign(usecase_id="UC", test_cases=[
        tc(1, purpose="Checks the OTP expires."),                                   # unexplained
        tc(2, purpose="Checks the One-Time Password (OTP) expires."),               # explained
        tc(3, purpose="Checks the one-time password expires; OTP is resent."),      # glossary words present
        tc(4, purpose="Checks the PDF receipt and SMS arrive."),                    # common
        tc(5, purpose="Checks rule BR-EDD-01 when status is DRAFT."),               # ID and state word
    ])
    issues = check_design(d, GLOSSARY, COMMON)
    flagged = {i.test_id for i in issues if i.rule == "abbreviation"}
    assert flagged == {"T1"}
    assert "One-Time Password" in next(i.message for i in issues if i.test_id == "T1")


def test_chatbot_messages_may_contain_abbreviations_but_portal_steps_may_not():
    t = tc(1, steps=["what is my USN format?"])
    assert check_design(TestDesign(usecase_id="UC", test_cases=[t]), GLOSSARY, COMMON, conversational=True) == []
    r = rules(check_design(TestDesign(usecase_id="UC", test_cases=[t]), GLOSSARY, COMMON, conversational=False))
    assert ("T1", "abbreviation") in r


def test_long_and_multi_action_portal_steps_are_flagged():
    long_step = " ".join(["word"] * 35)
    d = TestDesign(usecase_id="UC", test_cases=[tc(1, steps=[long_step, "Enter the amount and then click Pay"])])
    r = rules(check_design(d, GLOSSARY, COMMON, conversational=False))
    assert ("T1", "long_step") in r and ("T1", "multi_action") in r


def test_missing_explanations_flagged():
    r = rules(check_design(TestDesign(usecase_id="UC", test_cases=[tc(1, purpose="", business_impact="")]),
                           GLOSSARY, COMMON))
    assert ("T1", "missing") in r


def test_priority_and_perspective_coverage():
    d = TestDesign(usecase_id="UC", test_cases=[tc(i, priority="High") for i in range(10)])  # all End user
    issues = check_design(d, GLOSSARY, COMMON)
    cov = next(i for i in issues if i.rule == "priority_coverage")
    assert "Critical" in cov.message and "Low" in cov.message
    assert any(i.rule == "perspective_coverage" and "Business" in i.message for i in issues)


def test_sorted_critical_first_and_renumbered():
    d = TestDesign(usecase_id="SCN-01", test_cases=[
        tc(1, priority="Low"), tc(2, priority="Critical", perspective="Business"),
        tc(3, priority="Medium"), tc(4, priority="Critical", perspective="End user")])
    sort_and_renumber(d)
    assert [t.priority.value for t in d.test_cases] == ["Critical", "Critical", "Medium", "Low"]
    assert d.test_cases[0].perspective.value == "End user"
    assert [t.id for t in d.test_cases] == [f"TC-SCN-01-00{i}" for i in range(1, 5)]


class ReviewLLM(LLMClient):
    """First call: a design with problems. Second call (review round): the fixes + a new Low test."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def complete(self, system, user, role=""):
        self.calls.append(user)
        if len(self.calls) == 1:
            tests = [tc(i, priority=p, perspective=v).model_dump(mode="json") for i, (p, v) in enumerate(
                [("Critical", "Business"), ("High", "End user"), ("High", "Business"), ("Medium", "End user"),
                 ("Medium", "Both"), ("High", "End user"), ("Critical", "End user"), ("Medium", "Business")], 1)]
            tests[1]["expected_result"] = "Works correctly."
            return json.dumps({"usecase_id": "UC", "test_cases": tests, "gaps": []})
        fixed = tc(2, expected_result="Shows 9:00 PM with the hostel rules as source.").model_dump(mode="json")
        low = tc(2, priority="Low", title="Curfew question with a typo is understood").model_dump(mode="json")
        return json.dumps({"usecase_id": "UC", "test_cases": [fixed, low], "gaps": []})


def _understanding():
    return UseCaseUnderstanding(usecase_id="UC-9", summary="s", target_agent="a", personas=["student"],
                                user_intents=["i"], business_rules=["r"], knowledge_sources=["k"])


def test_review_round_fixes_issues_and_fills_missing_priority(tmp_path):
    llm = ReviewLLM()
    designer = TestDesigner(llm, {"domain_context": "", "personas": ""})
    d = designer.run(_understanding())
    assert len(llm.calls) == 2 and "review_findings" in llm.calls[1] and "vague_expected" in llm.calls[1]
    assert len(d.test_cases) == 9                                   # 8 + 1 new Low test, fix replaced in place
    assert d.test_cases[-1].priority == Priority.low
    assert designer.last_issues == []
    assert [t.id for t in d.test_cases][:2] == ["TC-UC-9-001", "TC-UC-9-002"]
    designer.export_csv(d, tmp_path / "t.csv")
    designer.export_quality(d, tmp_path / "q.md")
    rows = list(csv.reader((tmp_path / "t.csv").open(encoding="utf-8-sig")))
    head = rows[0]
    for col in ("Purpose", "Perspective", "Why this Priority", "Business Impact", "Priority"):
        assert col in head
    pr = [r[head.index("Priority")] for r in rows[1:]]
    assert pr == sorted(pr, key=["Critical", "High", "Medium", "Low"].index)
    assert "| Low | 1 |" in (tmp_path / "q.md").read_text()


def test_prompt_adapts_steps_to_chatbot_or_portal():
    chat = TestDesigner(ReviewLLM(), {"domain_context": "", "personas": ""})
    portal = TestDesigner(ReviewLLM(), {"domain_context": "", "personas": "",
                                        "system_kind": "an application or portal used through screens and forms"})
    kw = dict(skeleton="", glossary="", common_terms="")
    assert "literal messages the user types" in chat.system_prompt(**kw)
    assert "user's actions in the application" in portal.system_prompt(**kw)
    assert "Critical" in portal.system_prompt(**kw) and "End user" in portal.system_prompt(**kw)
