from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from src.state.state import DecisioState
from src.agents.screening_agent import screening_agent
from src.agents.retrieval_agent import retrieval_agent
from src.agents.hypothesis_agent import hypothesis_update_agent


def post_intake_parallel_agent(state: DecisioState) -> DecisioState:
    """
    Run work that can happen immediately after incident intake in parallel.

    - screening_agent: computes severity/safety/risk + escalation gates
    - retrieval_agent: pulls similar historical patterns (can optionally adjust risk/escalation)
    - hypothesis_update_agent: computes initial confidence + hypotheses so that
      confidence > 0% is visible immediately after the first user message.

    Merge policy:
    - Screening owns `incident_card` and overall status.
    - Retrieval contributes `retrieved_patterns` / `memory_guidance` fields.
    - Hypothesis agent contributes `confidence`, `hypotheses`, `risk_score`.
    - For overlapping numeric/boolean escalation fields:
        - risk_score = max(screening, retrieval, hypothesis) (highest risk wins)
        - escalation_triggered = OR
        - escalation_reasons = concatenated unique list (screening first)
    """
    if state is None:
        state = {}

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [
            ex.submit(screening_agent, dict(state)),
            ex.submit(retrieval_agent, dict(state)),
            ex.submit(hypothesis_update_agent, dict(state)),
        ]
        for f in as_completed(futs):
            try:
                r = f.result() or {}
                if isinstance(r, dict) and r:
                    results.append(r)
            except Exception:
                # Best-effort: if one branch fails, keep the other.
                continue

    screening = next((r for r in results if r.get("current_node") == "screening"), {}) or {}
    retrieval = next((r for r in results if r.get("current_node") == "retrieval"), {}) or {}
    hypothesis = next((r for r in results if r.get("current_node") == "hypothesis_update"), {}) or {}

    merged: dict = {}
    merged.update(screening)

    # Add retrieval outputs that don't conflict with screening’s card/status.
    for k in ("retrieved_patterns", "retrieval_confidence", "memory_guidance"):
        if k in retrieval:
            merged[k] = retrieval.get(k)

    # Apply initial confidence + hypotheses from hypothesis agent so the UI shows > 0%
    # immediately after the first user message (before any Q&A turns).
    if hypothesis.get("confidence") is not None:
        merged["confidence"] = hypothesis["confidence"]
    if hypothesis.get("hypotheses"):
        merged["hypotheses"] = hypothesis["hypotheses"]

    # Merge escalation + risk defensively (take the highest value from all three agents).
    scr_risk = screening.get("risk_score")
    ret_risk = retrieval.get("risk_score")
    hyp_risk = hypothesis.get("risk_score")
    risk_vals = []
    for raw in (scr_risk, ret_risk, hyp_risk):
        try:
            if raw is not None:
                risk_vals.append(float(raw))
        except Exception:
            pass
    if risk_vals:
        merged["risk_score"] = max(risk_vals)

    merged["escalation_triggered"] = (
        bool(screening.get("escalation_triggered"))
        or bool(retrieval.get("escalation_triggered"))
        or bool(hypothesis.get("escalation_triggered"))
    )

    reasons: list[str] = []
    for src in (screening, retrieval, hypothesis):
        for r in (src.get("escalation_reasons") or []):
            rr = str(r).strip()
            if rr and rr not in reasons:
                reasons.append(rr)
    if reasons:
        merged["escalation_reasons"] = reasons

    merged["current_node"] = "post_intake_parallel"
    # Keep screening’s status if present, otherwise fall back.
    merged["status"] = screening.get("status") or merged.get("status") or "DIAGNOSIS_LOOP"
    return merged

