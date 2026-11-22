"""Requirement Troubleshooter: finds where requirements are written, never invents sources."""
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

from qa_agents import service  # noqa: E402
from qa_agents.core.llm import LLMClient, MockLLM  # noqa: E402
from qa_agents.troubleshoot.agent import Troubleshooter  # noqa: E402
from qa_agents.troubleshoot.index import RequirementIndex, stem  # noqa: E402

SAMPLES = str(ROOT / "tests" / "fixtures" / "samples")


@pytest.fixture(scope="module")
def batch(tmp_path_factory):
    d = tmp_path_factory.mktemp("batch")
    pv = service.preview([SAMPLES], batch_dir=d, log=lambda *_: None)
    service.run_batch(pv, until="design", log=lambda *_: None)          # mock LLM: creates test cases
    return d


@pytest.fixture(scope="module")
def ts(batch):
    return Troubleshooter(MockLLM(), RequirementIndex.load(batch))


def test_stemming_matches_word_forms():
    assert stem("expiry") == stem("expires") == stem("expired") == stem("expiration")


@pytest.mark.parametrize("question,expected_id,where", [
    ("What does BR-GRV-02 say?", "BR-GRV-02", "3_Business_Rules"),
    ("Where is the OTP expiry rule written?", "FR-EDD-01", "2_Functional_Requirements"),
    ("Which requirement says the fee is non-refundable?", "BR-EDD-04", "3_Business_Rules"),
    ("How many copies can a student order?", "FR-EDD-02", "2_Functional_Requirements"),
])
def test_finds_where_requirement_is_written(ts, question, expected_id, where):
    a = ts.ask(question)
    assert a.found
    assert a.sources[0].item_id == expected_id and where in a.sources[0].label
    assert a.impact and a.suggestion


def test_conflicting_values_surface_the_right_conflict(ts):
    a = ts.ask("Where is the availability target mentioned?")
    assert a.found and a.conflicts[0].startswith("CF-") and "99" in a.conflicts[0]
    assert a.conflicts[0].split(":")[0] in a.suggestion


def test_not_in_documents_says_so_and_suggests_a_gap(ts):
    a = ts.ask("What is the dress code for students?")
    assert not a.found
    assert "not stated" in a.answer.lower()
    assert "Raise a gap" in a.suggestion
    assert a.related_tests == [] and a.conflicts == []
    assert 1 <= len(a.sources) <= 8           # closest related requirements are still offered


def test_question_about_a_test_case(ts):
    tc = ts.index.tests[0][1]
    a = ts.ask(f"Which requirement is {tc.id} based on?")
    assert tc.id in a.answer


def test_related_tests_when_tests_trace_to_the_requirement(batch):
    idx = RequirementIndex.load(batch)
    scn, tc = idx.tests[0]
    tc.traceability = ["BR-EDD-04"]                     # simulate a test tracing to a real BRD rule
    a = Troubleshooter(MockLLM(), idx).ask("What does BR-EDD-04 say?")
    assert any(t.id == tc.id and "traces to" in t.why for t in a.related_tests)


class FakeLLM(LLMClient):
    """Returns a fixed reply; cites S1 (real) and S99 (invented)."""
    def complete(self, system, user, role=""):
        self.last_user = user
        return json.dumps({"found": True, "answer": "Max 10 copies [S1] and also 99 copies [S99].",
                           "used_sources": ["S1", "S99"], "impact": "TC tests at risk.", "suggestion": "Use S1."})


def test_ai_answer_cannot_cite_sources_that_were_not_found(batch):
    llm = FakeLLM()
    a = Troubleshooter(llm, RequirementIndex.load(batch)).ask("How many copies can a student order?")
    assert a.mode == "ai"
    assert "[S1]" in a.answer and "[S99]" not in a.answer
    assert "SOURCES:" in llm.last_user and "[S1]" in llm.last_user


def test_ai_failure_falls_back_to_offline_answer(batch):
    class Broken(LLMClient):
        def complete(self, *a, **k):
            raise RuntimeError("quota exceeded")
    a = Troubleshooter(Broken(), RequirementIndex.load(batch)).ask("What does BR-GRV-02 say?")
    assert a.mode == "offline" and a.found


def test_index_requires_read_documents(tmp_path):
    with pytest.raises(FileNotFoundError, match="preview"):
        RequirementIndex.load(tmp_path)
