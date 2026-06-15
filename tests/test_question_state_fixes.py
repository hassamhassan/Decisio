"""
Unit tests for question deduplication, count semantics, and cleared pending questions.
No LLM calls except where patched.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.agents.answer_interpreter_agent import answer_interpreter_agent
from src.agents.question_agent import _is_duplicate, _norm_question_text


def test_norm_question_text_collapses_whitespace():
    assert _norm_question_text("  Foo   Bar\n\tbaz  ") == "foo bar baz"


def test_is_duplicate_identical_after_normalization():
    history = [{"question": "Check  CMP-01\npressure  gauge."}]
    assert _is_duplicate("Check CMP-01 pressure gauge.", history, threshold=0.65)


def test_is_duplicate_not_triggered_for_unrelated():
    history = [{"question": "What is the suction temperature on the chiller?"}]
    assert not _is_duplicate("Confirm the status of the backup diesel generator.", history)


def test_answer_interpreter_does_not_increment_questions_asked_count():
    """Only question_agent should bump questions_asked_count."""
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(
        content='{"facts": [], "signals": [], "contradictions": [], "answer_quality": "complete", "step_cleared": true}'
    )
    with patch("src.agents.answer_interpreter_agent.get_llm_fast", return_value=fake_llm):
        state = {
            "user_answer": "12 bar, within range",
            "current_question": {
                "question": "What is discharge pressure?",
                "category": "downstream_equipment",
            },
            "qa_history": [],
            "facts": [],
            "current_diagnostic_step": 3,
            "questions_asked_count": 5,
            "incident_card": {},
        }
        out = answer_interpreter_agent(state)
    assert "questions_asked_count" not in out
    assert out.get("qa_history") and len(out["qa_history"]) == 1


def test_decision_brief_agent_clears_questions():
    from src.agents.decision_brief_agent import decision_brief_agent

    minimal_brief_json = """
    {
      "analysis_summary": "Test",
      "root_cause_hypothesis": "Test",
      "options": [
        {"option_id": 1, "title": "A", "description": "Shutdown CMP-01 and inspect bearings this shift",
         "risks": [], "constraints": [], "confidence": 0.5, "risk_level": "low", "recommended": false, "eta": "1h"},
        {"option_id": 2, "title": "B", "description": "Restart CMP-01 at 60% load under monitoring",
         "risks": [], "constraints": [], "confidence": 0.6, "risk_level": "medium", "recommended": true, "eta": "30m"},
        {"option_id": 3, "title": "C", "description": "Isolate CMP-01 and switch to standby unit",
         "risks": [], "constraints": [], "confidence": 0.5, "risk_level": "medium", "recommended": false, "eta": "45m"}
      ],
      "risk_summary": "Test",
      "safety_constraints": [],
      "escalation_guidance": "Test",
      "requires_escalation": false,
      "decision_authority": "Technician",
      "escalation_path": "L1"
    }
    """
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content=minimal_brief_json.strip())
    state = {
        "incident_card": {
            "incident_id": "test-id",
            "asset_id": "CMP-01",
            "normalized_summary": "Vibration",
            "severity": "medium",
            "safety_level": "unknown",
        },
        "hypotheses": [],
        "facts": [],
        "qa_history": [],
        "safety_constraints": [],
        "safety_blocks": [],
        "escalation_triggered": False,
        "confidence": 0.5,
        "risk_score": 5.0,
        "questions": [{"question": "stale pending"}],
        "company_id": 1,
    }
    with patch("src.agents.decision_brief_agent.get_llm_for_brief", return_value=fake_llm):
        with patch(
            "src.agents.decision_brief_agent.sanitize_decision_brief",
            side_effect=lambda r, sc, sb: (r, False),
        ):
            out = decision_brief_agent(state)
    assert out.get("questions") == []


def test_escalation_agent_clears_questions_pending_config():
    from src.agents.escalation_agent import escalation_agent

    state = {
        "incident_card": {"incident_id": "x", "asset_id": "CMP-01"},
        "qa_history": [],
        "hypotheses": [],
        "facts": [],
        "decision_brief": {},
        "safety_constraints": [],
        "safety_blocks": [],
        "escalation_reasons": ["test"],
        "failed_attempts": 0,
        "risk_score": 5.0,
        "confidence": 0.5,
        "contradictions": [],
        "company_id": 999999,
        "questions": [{"question": "stale"}],
    }
    out = escalation_agent(state)
    assert out.get("questions") == []
