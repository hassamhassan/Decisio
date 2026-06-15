import pytest
from src.agents.decision_brief_agent import decision_brief_agent
from src.agents.escalation_agent import escalation_agent

def test_decision_brief_agent_three_options():
    # Deep Test: Verify the exact 3 options generated unless escalated
    test_state = {
        "incident_card": {
            "asset_id": "CMP-01",
            "normalized_summary": "Machine shaking",
            "severity": "high",
        },
        "symptoms": ["shaking"],
        "hypotheses": [{"description": "motor failure", "probability": 0.8, "category": "technical"}, {"description": "loose belt", "probability": 0.2, "category": "technical"}],
        "facts": [{"key": "observation", "value": "oil leak spotted", "confidence": 0.7}],
        "safety_constraints": [],
        "safety_blocks": [],
        "qa_history": [],
        "retrieved_patterns": [],
        "escalation_triggered": False,
        "company_id": 1,
    }
    
    brief_update = decision_brief_agent(test_state)
    assert brief_update is not None
    assert "decision_brief" in brief_update
    
    brief = brief_update["decision_brief"]
    assert "options" in brief
    
    # We enforce exactly 3 options in the rules
    # This might fail if the LLM hallucinated, but tests the instruction
    assert len(brief["options"]) == 3, f"Expected 3 options, got {len(brief['options'])}"

def test_decision_brief_agent_escalation_suppression():
    # When escalated, brief still carries exactly 3 options (UI contract) but flags escalation.
    test_state = {
        "incident_card": {"asset_id": "CMP-01"},
        "escalation_triggered": True,
        "escalation_reasons": ["Uncertain root cause"],
        "company_id": 1,
    }

    brief_update = decision_brief_agent(test_state)
    brief = brief_update["decision_brief"]

    assert brief.get("requires_escalation") is True
    assert len(brief["options"]) == 3

def test_escalation_agent_routing():
    # Deep Test: Ensure escalation agent maps rules correctly
    test_state = {
        "incident_card": {"asset_id": "CMP-01"},
        "confidence": 0.40,  # Below threshold triggers escalation
        "safety_interlock": False,
        "process_failure_suspected": False,
        "company_id": 1,
    }
    
    esc_update = escalation_agent(test_state)
    assert esc_update is not None
    assert "escalation" in esc_update
    
    escalation = esc_update["escalation"]
    # If no levels are configured, it sends pending_config. Otherwise it has escalation_level.
    if escalation.get("pending_config"):
        assert escalation.get("status") == "PENDING_ESCALATION_CONFIG"
    else:
        assert escalation["escalation_level"] > 0
    
    reasons_str = " ".join(escalation.get("escalation_reasons", []))
    # It might lack an explicit 'reason' key, test against reasons summary if needed, but not strictly bound.
