"""
Decisio — Post-Answer Parallel Agent

Runs expensive post-answer computations in parallel to reduce latency:
- Hypothesis update (confidence + hypotheses)
- Safety constraint evaluation (constraints/blocks/escalation)

These are largely independent once `answer_interpreter_agent` has appended the
latest facts/Q&A. We merge their returned state updates.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from src.state.state import DecisioState
from src.agents.hypothesis_agent import hypothesis_update_agent
from src.agents.safety_agent import safety_constraint_agent


def post_answer_parallel_agent(state: DecisioState) -> DecisioState:
    if state is None:
        state = {}

    # Run both nodes concurrently (they each call the LLM and are IO-bound).
    updates: list[dict] = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [
            ex.submit(hypothesis_update_agent, dict(state)),
            ex.submit(safety_constraint_agent, dict(state)),
        ]
        for f in as_completed(futs):
            try:
                u = f.result() or {}
                if isinstance(u, dict) and u:
                    updates.append(u)
            except Exception:
                # Fail open: if one branch errors, the other can still proceed.
                continue

    merged: dict = {}
    for u in updates:
        merged.update(u)

    # Merge strategy:
    # - Keep hypotheses/confidence from hypothesis agent when present.
    # - Keep safety_* and escalation_* from safety agent when present.
    # When both provide risk_score, prefer safety's risk_score because it can apply
    # mandatory risk adjustments and blocks.
    if "risk_score" in merged:
        # If both ran, `merged` currently reflects whichever finished last.
        # Force safety to win when it provided a risk_score.
        for u in updates:
            if u.get("current_node") == "safety_constraint" and "risk_score" in u:
                merged["risk_score"] = u["risk_score"]
                break

    merged["current_node"] = "post_answer_parallel"
    return merged

