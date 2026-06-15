#!/usr/bin/env python3
"""
Smoke-check the LangGraph pipeline wiring without a live OpenAI call.

Run from repo root:
  python scripts/graph_flow_smoke.py

Exercises:
  - Graph compile (intake + answer + outcome)
  - Fact formatting used across agents (legacy string facts must not crash)
  - decision_brief_agent clears ``questions`` when LLM is mocked
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from src.graph import build_answer_graph, build_graph, build_outcome_graph
    from src.agents.decision_brief_agent import decision_brief_agent
    from src.agents.prompt_context import format_fact_line, fact_value_only

    # ── Graphs compile ──────────────────────────────────────────────
    build_graph()
    build_answer_graph()
    build_outcome_graph()
    print("ok: graphs compile")

    # ── Fact helpers (A→Z agents share these) ─────────────────────────
    assert "oil" in format_fact_line({"key": "k", "value": "oil leak"})
    assert "- oil leak spotted" in format_fact_line("oil leak spotted")
    assert fact_value_only({"value": "x"}) == "x"
    assert fact_value_only("plain") == "plain"
    print("ok: format_fact_line / fact_value_only")

    # ── decision_brief clears questions (mock LLM) ────────────────────
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
            "incident_id": "smoke",
            "asset_id": "CMP-01",
            "normalized_summary": "Vibration",
            "severity": "medium",
            "safety_level": "unknown",
        },
        "hypotheses": [],
        "facts": ["legacy string fact"],
        "qa_history": [],
        "safety_constraints": [],
        "safety_blocks": [],
        "escalation_triggered": False,
        "confidence": 0.5,
        "risk_score": 5.0,
        "questions": [{"question": "stale"}],
        "company_id": 1,
    }
    with patch("src.agents.decision_brief_agent.get_llm_for_brief", return_value=fake_llm):
        with patch(
            "src.agents.decision_brief_agent.sanitize_decision_brief",
            side_effect=lambda r, sc, sb: (r, False),
        ):
            out = decision_brief_agent(state)
    assert out.get("questions") == [], out
    print("ok: decision_brief_agent tolerates legacy facts and clears questions")

    print("\nAll graph_flow_smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
