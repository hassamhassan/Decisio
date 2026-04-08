from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from src.state.state import DecisioState
from src.agents.screening_agent import screening_agent
from src.agents.retrieval_agent import retrieval_agent


def post_intake_parallel_agent(state: DecisioState) -> DecisioState:
    """
    Run work that can happen immediately after incident intake in parallel.

    - screening_agent: computes severity/safety/risk + escalation gates
    - retrieval_agent: pulls similar historical patterns (can optionally adjust risk/escalation)

    Merge policy:
    - Screening owns `incident_card` and overall status.
    - Retrieval contributes `retrieved_patterns` / `memory_guidance` fields.
    - For overlapping numeric/boolean escalation fields:
        - risk_score = max(screening, retrieval) (retrieval may bump risk for recurrence)
        - escalation_triggered = OR
        - escalation_reasons = concatenated unique list (screening first)
    """
    if state is None:
        state = {}

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [
            ex.submit(screening_agent, dict(state)),
            ex.submit(retrieval_agent, dict(state)),
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

    merged: dict = {}
    merged.update(screening)

    # Add retrieval outputs that don't conflict with screening’s card/status.
    for k in ("retrieved_patterns", "retrieval_confidence", "memory_guidance"):
        if k in retrieval:
            merged[k] = retrieval.get(k)

    # Merge escalation + risk defensively.
    scr_risk = screening.get("risk_score")
    ret_risk = retrieval.get("risk_score")
    try:
        scr_val = float(scr_risk) if scr_risk is not None else None
    except Exception:
        scr_val = None
    try:
        ret_val = float(ret_risk) if ret_risk is not None else None
    except Exception:
        ret_val = None
    if scr_val is not None or ret_val is not None:
        merged["risk_score"] = max(v for v in (scr_val, ret_val) if v is not None)

    merged["escalation_triggered"] = bool(screening.get("escalation_triggered")) or bool(
        retrieval.get("escalation_triggered")
    )

    reasons: list[str] = []
    for src in (screening, retrieval):
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

