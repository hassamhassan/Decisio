"""
Decisio — Main Entry Point (Full Interactive Pipeline)

Interactive CLI that runs the complete decision LOOP:
  Report → Screening → Questions → Decision Brief
  → Execute → Outcome → Memory Write / Re-diagnose / Escalate

Per the draft §5: "Decisio is not a straight line (report→fix).
It is a decision loop."
"""

import json
import sys

from dotenv import load_dotenv

load_dotenv()

from src.graph import build_graph, build_answer_graph, build_outcome_graph
from src.state.state import (
    CONFIDENCE_THRESHOLD,
    DIAGNOSTIC_CATEGORIES,
    DIAGNOSTIC_CATEGORY_LABELS,
    INCIDENT_STATUSES,
    MAX_TOTAL_QUESTIONS,
)


def print_header():
    print()
    print("=" * 70)
    print("  ⚙️  DECISIO — Operational Decision Support System")
    print("=" * 70)
    print()
    print("  Full loop: Report → Diagnosis → Brief → Execute → Outcome → Memory")
    print()
    print("  Type 'quit' to stop at any time.")
    print("─" * 70)


def print_incident_card(card: dict):
    print()
    print("─" * 70)
    print("🗂️  INCIDENT CARD")
    print("─" * 70)
    print(f"  ID:         {card.get('incident_id', 'N/A')}")
    print(f"  Summary:    {card.get('normalized_summary', 'N/A')}")
    print(f"  Asset:      {card.get('asset_id', 'Not specified')}")
    print(f"  Severity:   {card.get('severity', 'N/A')}")
    print(f"  Safety:     {card.get('safety_level', 'N/A')}")
    print(f"  Impact:     {card.get('impact', 'N/A')}")
    print(f"  Scope:      {card.get('scope', 'N/A')}")
    print(f"  Risk Score: {card.get('initial_risk_score', 'N/A')}")
    print(f"  Symptoms:   {', '.join(card.get('symptoms', []))}")


def print_patterns(patterns: list):
    if not patterns:
        print()
        print("  ℹ️  No similar past incidents in Decision Memory — using LLM reasoning only.")
        return
    print()
    print("─" * 70)
    print("🔍 SIMILAR PAST INCIDENTS")
    print("─" * 70)
    for p in patterns:
        esc = " ⚠️ MUST ESCALATE" if p.get("must_escalate") else ""
        print(f"  • {p.get('title', 'N/A')} ({p.get('similarity_score', 0):.0%}){esc}")
        print(f"    Decision: {p.get('decision_taken', 'N/A')}")


def print_questions(questions: list, step: int):
    step_index = max(0, min(step - 1, 9))
    category = DIAGNOSTIC_CATEGORIES[step_index]
    label = DIAGNOSTIC_CATEGORY_LABELS[category]

    print()
    print("─" * 70)
    print(f"❓ DIAGNOSTIC QUESTIONS — Step {step}/10: {label}")
    print("─" * 70)
    for i, q in enumerate(questions, 1):
        cat_key = q.get("category", "?")
        cat_label = DIAGNOSTIC_CATEGORY_LABELS.get(cat_key, cat_key)
        print(f"\n  Q{i} [{cat_label}]")
        print(f"     {q.get('question', 'N/A')}")
        if q.get("blocking_safety_flag"):
            print("     ⚠️  BLOCKING SAFETY FLAG")


def print_decision_brief(brief: dict):
    print()
    print("=" * 70)
    print("📋 DECISION BRIEF")
    print("=" * 70)

    if brief.get("requires_escalation"):
        print("  ⚠️  ESCALATION REQUIRED")

    print(f"\n  Risk Summary:      {brief.get('risk_summary', 'N/A')}")
    print(f"  Confidence:        {brief.get('overall_confidence', 0):.0%}")
    print(f"  Decision Authority: {brief.get('decision_authority', 'N/A')}")
    print(f"  Escalation Path:   {brief.get('escalation_path', 'N/A')}")

    for opt in brief.get("options", []):
        rec = " ⭐ RECOMMENDED" if opt.get("recommended") else ""
        print(f"\n  ── Option {opt.get('option_id', '?')}{rec} ──")
        print(f"  Title:       {opt.get('title', 'N/A')}")
        print(f"  Description: {opt.get('description', 'N/A')}")
        print(f"  Confidence:  {opt.get('confidence', 0):.0%}")
        if opt.get("risks"):
            print(f"  Risks:       {', '.join(opt['risks'])}")
        if opt.get("constraints"):
            print(f"  Constraints: {', '.join(opt['constraints'])}")

    if brief.get("safety_constraints"):
        print(f"\n  Safety Constraints:")
        for c in brief["safety_constraints"]:
            print(f"    • {c}")


def print_escalation(escalation: dict):
    print()
    print("=" * 70)
    print("🔴 ESCALATION PACKAGE")
    print("=" * 70)
    level = escalation.get("escalation_level", "?")
    name = escalation.get("escalation_level_name", "Unknown")
    print(f"  Level:      {level} — {name}")
    print(f"  Urgency:    {escalation.get('urgency', 'N/A')}")
    print(f"  Expertise:  {escalation.get('recommended_expertise', 'N/A')}")
    print(f"  Summary:    {escalation.get('escalation_summary', 'N/A')}")

    if escalation.get("safety_warnings"):
        print(f"\n  ⚠️  Safety Warnings:")
        for w in escalation["safety_warnings"]:
            print(f"    • {w}")

    if escalation.get("what_was_tried"):
        print(f"\n  What was tried:")
        for t in escalation["what_was_tried"]:
            print(f"    • {t}")


def print_status(state: dict):
    print()
    print("─" * 70)
    risk = state.get("risk_score", "?")
    conf = state.get("confidence", 0)
    step = state.get("current_diagnostic_step", 1)
    asked = state.get("questions_asked_count", 0)
    esc = state.get("escalation_triggered", False)
    status = state.get("status", "?")
    failed = state.get("failed_attempts", 0)
    print(f"  Status: {status} | Risk: {risk} | Confidence: {conf:.0%} | "
          f"Step: {step}/10 | Questions: {asked}/{MAX_TOTAL_QUESTIONS}")
    print(f"  Escalation: {'YES' if esc else 'No'} | Failed Attempts: {failed}")

    if state.get("escalation_reasons"):
        print(f"  Escalation reasons:")
        for r in state["escalation_reasons"]:
            print(f"    ⚠️  {r}")

    if state.get("hypotheses"):
        print(f"\n  Top hypotheses:")
        for h in state["hypotheses"][:3]:
            print(f"    • {h.get('description', '?')} ({h.get('probability', 0):.0%})")

    print("─" * 70)


def main():
    print_header()

    # Build graphs
    intake_graph = build_graph()
    answer_graph = build_answer_graph()
    outcome_graph = build_outcome_graph()

    while True:
        print()
        report = input("📝 Enter incident report (or 'quit'): ").strip()

        if not report:
            print("  ⚠️  Please enter a report.")
            continue

        if report.lower() in ("quit", "exit", "q"):
            print("\n  👋 Goodbye!\n")
            break

        # ── Phase 1: Intake → Screening → Retrieval → First Questions ──
        print(f"\n  ⏳ Processing incident...")

        try:
            state = intake_graph.invoke({
                "report": report,
                "current_diagnostic_step": 1,
                "questions_asked_count": 0,
                "qa_history": [],
                "facts": [],
                "hypotheses": [],
                "contradictions": [],
                "safety_constraints": [],
                "safety_blocks": [],
                "escalation_triggered": False,
                "escalation_reasons": [],
                "confidence": 0.0,
                "failed_attempts": 0,
                "outcome": "pending",
                "status": "OPEN",
            })
        except Exception as e:
            print(f"\n  ❌ Error: {e}")
            print("     Make sure OPENAI_API_KEY is set in .env")
            continue

        # Display initial results
        if state.get("screening_complete"):
            print_incident_card(state.get("incident_card", {}))
            print_patterns(state.get("retrieved_patterns", []))

        # Check for clarification question
        while state.get("clarification_question"):
            print(f"\n  🤖 Clarification Needed: {state['clarification_question']}")
            answer = input("  📨 Your answer: ").strip()

            if answer.lower() in ("quit", "exit", "q"):
                print("\n  👋 Goodbye!\n")
                sys.exit(0)

            print(f"\n  ⏳ Processing clarification...")
            state["report"] = state.get("report", "") + f"\n\n[User Clarification]: {answer}"
            qa_hist = state.get("qa_history") or []
            qa_hist.append({"question": state.get("clarification_question", ""), "answer": answer, "category": "clarification", "diagnostic_step": 1, "signals": []})
            state["qa_history"] = qa_hist
            state.pop("clarification_question", None)
            
            try:
                state = intake_graph.invoke(state)
            except Exception as e:
                print(f"  ❌ Error processing text: {e}")
                break
                
            if state.get("screening_complete"):
                print_incident_card(state.get("incident_card", {}))
                print_patterns(state.get("retrieved_patterns", []))

        # Check for immediate escalation
        if state.get("escalation_triggered"):
            if state.get("escalation"):
                print_escalation(state["escalation"])
            if state.get("decision_brief"):
                print_decision_brief(state["decision_brief"])
            print("\n  🔴 Immediate escalation triggered — skipping diagnosis loop.")
            continue

        # ── Phase 2: Iterative Diagnosis Loop ────────────────────────
        questions = state.get("questions", [])

        while questions and not state.get("escalation_triggered", False):
            step = state.get("current_diagnostic_step", 1)
            if step > 10:
                break

            print_questions(questions, step)
            print_status(state)

            # Get user answer
            print()
            print("  Answer the questions above (combine answers, or 'skip' / 'quit'):")
            answer = input("  📨 Your answer: ").strip()

            if answer.lower() in ("quit", "exit", "q"):
                print("\n  Generating Decision Brief with available information...\n")
                break

            if answer.lower() in ("skip", "s", ""):
                answer = "I don't know / skipped"

            # Pick the first question as the active one
            current_q = questions[0] if questions else {}

            # Process the answer through the sub-graph
            try:
                print(f"\n  ⏳ Analyzing answer...")
                state = answer_graph.invoke({
                    **state,
                    "user_answer": answer,
                    "current_question": current_q,
                })
            except Exception as e:
                print(f"  ❌ Error processing answer: {e}")
                break

            questions = state.get("questions", [])

            # Check if decision brief was generated
            if state.get("decision_brief"):
                break

            # Check confidence threshold
            confidence = state.get("confidence", 0.0)
            if confidence >= CONFIDENCE_THRESHOLD:
                print(f"\n  ✅ Confidence {confidence:.0%} reached threshold — generating Decision Brief...")
                break

        # ── Phase 3: Generate Decision Brief if not already done ─────
        if not state.get("decision_brief"):
            print(f"\n  ⏳ Generating Decision Brief...")
            try:
                from src.agents.decision_brief_agent import decision_brief_agent
                brief_update = decision_brief_agent(state)
                state.update(brief_update)
            except Exception as e:
                print(f"  ❌ Error generating brief: {e}")

        # Display escalation if triggered
        if state.get("escalation"):
            print_escalation(state["escalation"])

        # Display the Decision Brief
        if state.get("decision_brief"):
            print_decision_brief(state["decision_brief"])

        print_status(state)

        # ── Phase 4: Outcome Loop (§5 Steps 6-8) ────────────────────
        # This is the CRITICAL loop: Brief → Execute → Outcome → Memory
        print()
        print("=" * 70)
        print("  📌 DECISION LOOP — Report the outcome after execution")
        print("=" * 70)

        max_retries = 3
        while state.get("outcome", "pending") != "success" and state.get("failed_attempts", 0) < max_retries:
            failed = state.get("failed_attempts", 0)
            attempt_label = f" (attempt #{failed + 1})" if failed > 0 else ""

            print(f"\n  After executing the chosen decision{attempt_label}, report the outcome:")
            print("  Options: 'success' / 'failure' / describe what happened / 'skip' / 'quit'")
            outcome_input = input("  📊 Outcome: ").strip()

            if outcome_input.lower() in ("quit", "exit", "q", "skip", "s", ""):
                print("\n  ⏭️  Skipping outcome capture. Incident left as BRIEF_GENERATED.")
                break

            # Determine outcome category
            if outcome_input.lower() == "success":
                outcome_notes = "Resolution successful — trigger conditions normalized."
            elif outcome_input.lower() == "failure":
                outcome_notes = "Resolution failed — problem persists."
            else:
                outcome_notes = outcome_input

            # Process outcome
            try:
                print(f"\n  ⏳ Processing outcome...")
                state.update({
                    "outcome_notes": outcome_notes,
                    "status": "EXECUTING",
                })

                from src.agents.outcome_capture_agent import outcome_capture_agent
                outcome_update = outcome_capture_agent(state)
                state.update(outcome_update)
            except Exception as e:
                print(f"  ❌ Error processing outcome: {e}")
                break

            outcome = state.get("outcome", "failure")

            if outcome == "success":
                # ── Success: Write to Decision Memory ────────────────
                print(f"\n  ✅ Resolution successful!")
                print(f"  ⏳ Writing to Decision Memory...")

                try:
                    from src.agents.memory_write_agent import memory_write_agent
                    memory_update = memory_write_agent(state)
                    state.update(memory_update)

                    if state.get("memory_written"):
                        print("  💾 Decision pattern stored in Memory.")
                    else:
                        print("  ⚠️  Memory write skipped (Qdrant not available).")
                except Exception as e:
                    print(f"  ❌ Error writing memory: {e}")

                state["status"] = "CLOSED"
                break

            elif state.get("escalation_triggered"):
                # ── Escalation needed ────────────────────────────────
                print(f"\n  🔴 Escalation triggered after {state.get('failed_attempts', 0)} failed attempt(s).")
                print(f"     Reason: {state.get('escalation_reasons', ['Unknown'])[-1]}")

                try:
                    from src.agents.escalation_agent import escalation_agent as esc_agent
                    esc_update = esc_agent(state)
                    state.update(esc_update)
                    if state.get("escalation"):
                        print_escalation(state["escalation"])
                except Exception as e:
                    print(f"  ❌ Error generating escalation: {e}")

                state["status"] = "ESCALATED"

                # Expert capture after escalation resolution
                print(f"\n  After the expert resolves this, describe what they found:")
                print("  (or 'skip' to close without expert capture)")
                expert_input = input("  🎓 Expert notes: ").strip()

                if expert_input.lower() not in ("skip", "s", "", "quit", "q"):
                    try:
                        from src.agents.expert_capture_agent import expert_capture_agent
                        state["outcome_notes"] = expert_input
                        expert_update = expert_capture_agent(state)
                        state.update(expert_update)
                        if state.get("memory_written"):
                            print("  💾 Expert knowledge captured and stored.")
                    except Exception as e:
                        print(f"  ❌ Error capturing expert knowledge: {e}")
                break

            else:
                # ── Failure without escalation: retry ────────────────
                print(f"\n  ❌ Resolution failed (attempt #{state.get('failed_attempts', 0)}).")
                print(f"     Risk increased to {state.get('risk_score', '?')}")
                if state.get("safety_constraints"):
                    print(f"     Safety tightened: {state['safety_constraints'][-1]}")
                print(f"     Re-entering diagnosis with tighter constraints...")

                # Re-enter a shortened diagnosis loop
                try:
                    from src.agents.question_agent import question_agent
                    q_update = question_agent(state)
                    state.update(q_update)

                    questions = state.get("questions", [])
                    if questions:
                        step = state.get("current_diagnostic_step", 1)
                        print_questions(questions, step)
                        print()
                        answer = input("  📨 Additional info: ").strip()
                        if answer.lower() not in ("skip", "s", "", "quit", "q"):
                            state = answer_graph.invoke({
                                **state,
                                "user_answer": answer,
                                "current_question": questions[0],
                            })
                except Exception as e:
                    print(f"  ❌ Error in retry diagnosis: {e}")

                # Re-generate brief with new info
                try:
                    from src.agents.decision_brief_agent import decision_brief_agent
                    brief_update = decision_brief_agent(state)
                    state.update(brief_update)
                    if state.get("decision_brief"):
                        print_decision_brief(state["decision_brief"])
                except Exception as e:
                    print(f"  ❌ Error generating updated brief: {e}")

        # ── Final Status ─────────────────────────────────────────────
        print()
        print("=" * 70)
        final_status = state.get("status", "UNKNOWN")
        outcome = state.get("outcome", "pending")
        memory = "✅ Written" if state.get("memory_written") else "—"

        if outcome == "success":
            print(f"  ✅ INCIDENT CLOSED — {final_status}")
        elif final_status == "ESCALATED":
            print(f"  🔴 INCIDENT ESCALATED — {final_status}")
        else:
            print(f"  📋 INCIDENT STATUS: {final_status}")

        print(f"     Outcome: {outcome} | Memory: {memory} | "
              f"Failed attempts: {state.get('failed_attempts', 0)}")
        print("=" * 70)


if __name__ == "__main__":
    main()
