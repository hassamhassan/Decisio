"""
Decisio — LangGraph Workflow (Full Pipeline)

Wires all agents into a complete workflow with an iterative
diagnosis loop through the 10-step diagnostic framework.

Intake flow (guided, multi-turn via the API):
─────────────────────────────────────────────
  User sends initial message
      │
      ▼
  problem_intake  ── [intake_phase = "symptoms"]
      │ no symptoms in report
      │   → clarification_question set → END
      │   → API sends question to user; user replies; intake_graph re-invoked
      │ symptoms found
      ▼
  problem_intake  ── [intake_phase = "machine"]
      │   → clarification_question with DB machine list → END
      │   → API sends question; user replies with machine ID; re-invoked
      ▼
  problem_intake  ── [intake_phase = "complete"]
      │   → validates machine against DB; if invalid → stays in "machine"
      │   → if valid: clarification_question = None → proceeds below
      ▼
  incident_intake  ── builds structured Incident Card
      │
      ▼
  screening  ── severity / safety / risk scoring
      │ escalation trigger?
      ├─► escalation ──► END
      │
      ▼
  question_generation ──► END
      (returns first diagnostic question to client)

Answer loop (answer_graph, one turn per user answer):
──────────────────────────────────────────────────────
  answer_interpreter → hypothesis_update → safety_constraint
      → advance_step → diagnosis_router
          │ continue          │ done / escalate
          ▼                   ▼
    question_generation    post_qa_retrieval → decision_brief → END
          │
          ▼
         END  (question returned to client)

Clarification contract:
───────────────────────
  When problem_intake_agent sets `clarification_question`, pre_intake_router
  returns "end" → END.  The FastAPI layer (api.py  /answer endpoint):
    1. Detects `clarification_question` in state / `screening_complete` is False.
    2. Appends the user's reply as "[User Clarification]: <answer>" to state["report"].
    3. Re-invokes intake_graph so problem_intake_agent runs again with the new info.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from src.agents.problem_intake_agent import problem_intake_agent
from src.agents.incident_intake_agent import incident_intake_agent
from src.agents.screening_agent import screening_agent
from src.agents.retrieval_agent import retrieval_agent
from src.agents.question_agent import question_agent
from src.agents.answer_interpreter_agent import answer_interpreter_agent
from src.agents.hypothesis_agent import hypothesis_update_agent
from src.agents.safety_agent import safety_constraint_agent
from src.agents.decision_brief_agent import decision_brief_agent
from src.agents.escalation_agent import escalation_agent
from src.agents.outcome_capture_agent import outcome_capture_agent
from src.agents.memory_write_agent import memory_write_agent
from src.agents.expert_capture_agent import expert_capture_agent
from src.state.state import (
    CONFIDENCE_THRESHOLD,
    MAX_TOTAL_QUESTIONS,
    RISK_ESCALATION_THRESHOLD,
    DecisioState,
)


# ── Router functions ─────────────────────────────────────────────────


def pre_intake_router(state: DecisioState) -> str:
    """
    Route after problem_intake.

    Contract with the API:
    - If `clarification_question` is present in state, we END the graph run.
      The FastAPI layer detects this field in the response and sends the
      clarification question to the user. When the user replies, their
      answer is appended to `state['report']` and the intake_graph is
      invoked again (see `/api/incidents/{id}/answer` in `api.py`).
    - If no clarification is needed, proceed to `incident_intake`.
    """
    if state is None:
        state = {}
    if state.get("clarification_question"):
        # We need clarification (problem or machine name is missing).
        # Returning the special key "end" routes this node to END; the
        # outer API loop will handle asking the question and re-running
        # intake_graph after the user answers.
        return "end"
    
    # Otherwise, it's clear enough to build an incident card
    return "incident_intake"


def post_screening_router(state: DecisioState) -> str:
    """Route after screening: escalate or first diagnostic question.

    Decision Memory (vector) retrieval runs later — after Q&A — via
    ``post_qa_retrieval``, only when routing to the decision brief.
    """
    if state is None:
        state = {}
    if state.get("escalation_triggered"):
        return "escalation"
    return "question_generation"


def diagnosis_router(state: DecisioState) -> str:
    """
    Core diagnosis loop router.

    Decides whether to continue asking questions, generate the
    decision brief, or escalate.
    """
    # Check escalation
    if state.get("escalation_triggered"):
        return "escalation"


    # Check confidence threshold
    confidence = state.get("confidence", 0.0)
    if confidence >= CONFIDENCE_THRESHOLD:
        return "decision_brief"

    # Check question budget
    questions_asked = state.get("questions_asked_count", 0)
    if questions_asked >= MAX_TOTAL_QUESTIONS:
        return "decision_brief"

    # Check if all 10 steps completed
    current_step = state.get("current_diagnostic_step", 1)
    if current_step > 10:
        return "decision_brief"

    # Continue diagnosis
    return "question_generation"


def post_safety_router(state: DecisioState) -> str:
    """Route after safety check: escalate or continue loop."""
    if state is None:
        state = {}
    if state.get("escalation_triggered"):
        return "escalation"

    # Advance diagnostic step after completing a round
    return "diagnosis_router"


def outcome_router(state: DecisioState) -> str:
    """Route after outcome capture: retry, escalate, or close."""
    outcome = state.get("outcome", "")
    if outcome == "success":
        return "memory_write"
    if state.get("escalation_triggered"):
        return "escalation"
    # failure without escalation → retry diagnosis
    return "question_generation"


# ── Step advancer ────────────────────────────────────────────────────


def advance_diagnostic_step(state: DecisioState) -> DecisioState:
    """Advance to the next diagnostic step after a Q&A round if the step is cleared."""
    if state is None:
        state = {}
    current_step = state.get("current_diagnostic_step", 1)
    step_cleared = state.get("step_cleared", True)
    
    next_step = current_step + 1 if step_cleared else current_step

    return {
        "current_diagnostic_step": next_step,
        "should_continue_diagnosis": True,
    }


# ── Graph builder ────────────────────────────────────────────────────


def build_graph() -> StateGraph:
    """
    Build and compile the full Decisio LangGraph workflow.
    """
    graph = StateGraph(DecisioState)

    # ── Register all nodes ───────────────────────────────────────────
    graph.add_node("problem_intake", problem_intake_agent)
    graph.add_node("incident_intake", incident_intake_agent)
    graph.add_node("screening", screening_agent)
    graph.add_node("question_generation", question_agent)
    graph.add_node("answer_interpreter", answer_interpreter_agent)
    graph.add_node("hypothesis_update", hypothesis_update_agent)
    graph.add_node("safety_constraint", safety_constraint_agent)
    graph.add_node("advance_step", advance_diagnostic_step)
    graph.add_node("decision_brief", decision_brief_agent)
    # Retrieval once Q&A context exists, immediately before decision brief
    graph.add_node("post_qa_retrieval", retrieval_agent)
    graph.add_node("escalation", escalation_agent)
    graph.add_node("outcome_capture", outcome_capture_agent)
    graph.add_node("memory_write", memory_write_agent)
    graph.add_node("expert_capture", expert_capture_agent)

    # ── Entry point ──────────────────────────────────────────────────
    # New: first run a lightweight problem/machine intake, then the
    # existing incident_intake continues to build the Incident Card.
    graph.set_entry_point("problem_intake")

    # ── Linear flow: problem_intake → incident_intake → screening ────
    graph.add_conditional_edges(
        "problem_intake",
        pre_intake_router,
        {
            "incident_intake": "incident_intake",
            "end": END,
        },
    )
    graph.add_edge("incident_intake", "screening")

    # ── After screening: escalate or continue ────────────────────────
    graph.add_conditional_edges(
        "screening",
        post_screening_router,
        {
            "question_generation": "question_generation",
            "escalation": "escalation",
        },
    )

    # ── First-time question generation → END (return questions to client) ─
    graph.add_edge("question_generation", END)

    # ── Answer processing pipeline ───────────────────────────────────
    graph.add_edge("answer_interpreter", "hypothesis_update")
    graph.add_edge("hypothesis_update", "safety_constraint")
    graph.add_edge("safety_constraint", "advance_step")

    # ── After advancing: route to continue or generate brief ─────────
    graph.add_conditional_edges(
        "advance_step",
        diagnosis_router,
        {
            "question_generation": "question_generation",
            # When diagnosis is ready for a brief, first refresh patterns
            # with a retrieval pass that sees the full Q&A context.
            "decision_brief": "post_qa_retrieval",
            "escalation": "escalation",
        },
    )

    # ── Escalation ends the flow immediately
    graph.add_edge("escalation", END)

    # ── Post-questioning retrieval → decision brief → END ───────────
    graph.add_edge("post_qa_retrieval", "decision_brief")

    # ── Decision brief → END ─────────────────────────────────────────
    graph.add_edge("decision_brief", END)

    # ── Outcome loop (used by main.py) ───────────────────────────────
    graph.add_conditional_edges(
        "outcome_capture",
        outcome_router,
        {
            "memory_write": "memory_write",
            "escalation": "escalation",
            "question_generation": "question_generation",
        },
    )
    graph.add_edge("memory_write", END)
    graph.add_edge("expert_capture", END)

    return graph.compile()


# ── Build the answer-processing sub-graph ────────────────────────────


def build_answer_graph() -> StateGraph:
    """
    Build a sub-graph for processing a single answer.

        Flow: answer_interpreter → hypothesis_update → safety_constraint
          → advance_step → (question_generation → END
                             | post_qa_retrieval → decision_brief → END
                             | escalation → END)
    """
    graph = StateGraph(DecisioState)

    graph.add_node("answer_interpreter", answer_interpreter_agent)
    graph.add_node("hypothesis_update", hypothesis_update_agent)
    graph.add_node("safety_constraint", safety_constraint_agent)
    graph.add_node("advance_step", advance_diagnostic_step)
    graph.add_node("question_generation", question_agent)
    graph.add_node("decision_brief", decision_brief_agent)
    graph.add_node("escalation", escalation_agent)
    # Additional retrieval pass once questioning is complete
    graph.add_node("post_qa_retrieval", retrieval_agent)

    graph.set_entry_point("answer_interpreter")
    graph.add_edge("answer_interpreter", "hypothesis_update")
    graph.add_edge("hypothesis_update", "safety_constraint")
    graph.add_edge("safety_constraint", "advance_step")

    graph.add_conditional_edges(
        "advance_step",
        diagnosis_router,
        {
            "question_generation": "question_generation",
            # After questioning is done, refresh patterns then generate brief
            "decision_brief": "post_qa_retrieval",
            "escalation": "escalation",
        },
    )

    graph.add_edge("escalation", END)
    # For the answer subgraph, question_generation directly returns
    # questions to the client; retrieval is only used just before
    # the final decision brief.
    graph.add_edge("question_generation", END)
    graph.add_edge("post_qa_retrieval", "decision_brief")
    graph.add_edge("decision_brief", END)

    return graph.compile()


# ── Build the outcome sub-graph ──────────────────────────────────────


def build_outcome_graph() -> StateGraph:
    """
    Build a sub-graph for processing outcome + expert capture.

    Flow: outcome_capture → memory_write (success) or escalation (failure)
          expert_capture → END
    """
    graph = StateGraph(DecisioState)

    graph.add_node("outcome_capture", outcome_capture_agent)
    graph.add_node("memory_write", memory_write_agent)
    graph.add_node("expert_capture", expert_capture_agent)
    graph.add_node("escalation", escalation_agent)
    graph.add_node("post_qa_retrieval", retrieval_agent)
    graph.add_node("decision_brief", decision_brief_agent)

    graph.set_entry_point("outcome_capture")

    graph.add_conditional_edges(
        "outcome_capture",
        outcome_router,
        {
            "memory_write": "memory_write",
            "escalation": "escalation",
            "question_generation": END,  # will re-enter diagnosis via main.py
        },
    )

    graph.add_edge("memory_write", END)
    graph.add_edge("escalation", END)

    return graph.compile()


# ── CLI entry-point ──────────────────────────────────────────────────

if __name__ == "__main__":
    import json as _json

    sample_report = (
        "Unit 7 compressor tripped on high discharge temperature at 14:32. "
        "Vibration readings on the drive-end bearing were elevated last shift "
        "(12.4 mm/s vs. 7.0 mm/s baseline). Oil pressure is reading normal. "
        "No visible leaks but there is an unusual smell near the coupling guard. "
        "Asset ID: COMP-7-ALPHA."
    )

    print("=" * 70)
    print("DECISIO — Full Pipeline Run")
    print("=" * 70)
    print(f"\n📝 Report: {sample_report}\n")

    app = build_graph()
    result = app.invoke({
        "report": sample_report,
        "current_diagnostic_step": 1,
        "questions_asked_count": 0,
    })

    print("─" * 70)
    print("🗂️  INCIDENT CARD")
    print("─" * 70)
    print(_json.dumps(result.get("incident_card", {}), indent=2))

    print("\n" + "─" * 70)
    print("🔍 RETRIEVED PATTERNS")
    print("─" * 70)
    for p in result.get("retrieved_patterns", []):
        print(f"  - {p.get('title', '')} ({p.get('similarity_score', 0):.0%})")

    print("\n" + "─" * 70)
    print("❓ DIAGNOSTIC QUESTIONS")
    print("─" * 70)
    for i, q in enumerate(result.get("questions", []), 1):
        print(f"  Q{i} [{q.get('category', '?').upper()}]: {q.get('question', '')}")

    print("\n" + "=" * 70)
    print(f"Status: {result.get('status')} | Risk: {result.get('risk_score', '?')} | Escalation: {result.get('escalation_triggered', False)}")
    print("=" * 70)
