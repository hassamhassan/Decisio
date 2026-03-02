# Boundary, Safety & Multi-Tenant Implementation Summary

All requested fixes have been applied. This document lists where each requirement is implemented.

---

## 1. Boundary & Decision Execution Safety

### Programmatic sanitization
- **`src/sanitization.py`** (new)
  - `FORBIDDEN_PHRASES`: regex list for "step 1", "setpoint", "turn off", "disassemble", "set the", "open/close the valve", "torque to", "command sequence", "follow these steps", etc.
  - `sanitize_decision_brief(result, safety_constraints, safety_blocks)`: scans `options[].description`, `options[].title`, and `analysis_summary`; redacts matches with `[Description redacted: decision-level only; no execution steps.]`
  - Returns `(sanitized_result, had_violations)`; options are not removed.

### Integration
- **`src/agents/decision_brief_agent.py`**
  - After parsing LLM JSON, calls `sanitize_decision_brief(result, ...)` and uses the sanitized `result` for the brief.
  - Prompt boundary unchanged: "CRITICAL BOUNDARY: You must NEVER include repair steps, disassembly, command sequences, operational execution steps."

### Prompt boundaries verified
- **decision_brief_agent.py**: CRITICAL BOUNDARY in SYSTEM_PROMPT; decision-level only.
- **expert_capture_agent.py**: "CRITICAL BOUNDARIES — do NOT extract: repair steps, disassembly, setpoints, execution guidance."
- **memory_write_agent.py**: "Does NOT store: repair steps, operating instructions, setpoints."
- **escalation_agent.py**: "Do NOT include repair instructions — only decision context."
- **safety_agent.py**: Equipment rules and constraints only; no execution steps.

---

## 2. Hypothesis & Root Cause Layer Consistency

- **`src/state/state.py`**
  - `Hypothesis.root_cause_layer` default changed from `"root_cause"` to **`"symptom"`** (safe default).
- **`src/agents/hypothesis_agent.py`**
  - For each hypothesis from the LLM: `root_cause_layer = (h_data.get("root_cause_layer") or "symptom")`; normalized to one of `symptom` | `trigger` | `root_cause`, otherwise `"symptom"`.
- **`src/agents/decision_brief_agent.py`**
  - `symptom_only = all(h.get("root_cause_layer") == "symptom" for h in hypotheses)`; when True, context adds "Root cause is NOT isolated" and "Do NOT recommend internal machine actions."

---

## 3. Multi-Tenant Isolation & Data Scoping

### API
- **`api.py`**
  - `_load_state(incident_id, company_id=None)`: when `company_id` is set, calls `crud.get_incident(session, incident_id, company_id=company_id)` and returns `None` for wrong tenant (→ **404**).
  - In-memory: if `company_id` is set and `state["company_id"] != company_id`, returns `None`.
  - All incident routes use `_load_state(incident_id, company_id=user.company_id)`; redundant 403 checks removed.

### Data layer (already present from prior audit)
- `get_all_applicable_rules(equipment_type, severity, company_id=...)`
- `get_escalation_levels(company_id=...)`, `get_escalation_rules(company_id=...)`
- `get_asset(asset_id, company_id=...)`, `get_asset_type(..., company_id=...)`
- Retrieval agent: returns empty patterns when `company_id` is None.
- Memory write and expert capture: every stored pattern includes `company_id`.

---

## 4. Safety Constraint Enforcement

- **`src/state/state.py`**
  - **`DecisionOption.blocked_by_safety: bool = False`** added.
- **`src/agents/decision_brief_agent.py`**
  - When `safety_blocks` is non-empty: any option with `risk_level == "high"` is set `blocked_by_safety=True` and `recommended=False`.
  - If no option is recommended after that, the first non-blocked option is set `recommended=True`.
  - High-risk options are not removed; they are only marked and non-recommended.

### Escalation triggers (unchanged; documented)
- **`src/agents/safety_agent.py`**
  - Programmatic: `risk_score >= 8`, low confidence after question budget, `contradiction_count >= 3`, any safety_blocks, or LLM `requires_escalation`.
  - Module docstring updated to list these.

---

## 5. Webchat / Question Flow

- **`src/agents/question_agent.py`**
  - Comment added: deduplication via `_is_duplicate(..., qa_history)` and context-aware narrowing via current diagnostic step and prompt ("do not repeat already-completed steps").
- No separate "2–3 screening questions" before step 1: screening remains LLM classification; first user-facing questions are the first batch of 3 diagnostic questions (step 1). Specification can be extended later if required.

---

## 6. Governance, Audit & Memory Compliance

- **Memory write & expert capture**
  - Stored fields include: `company_id`, `decision_taken`, `must_escalate`, `root_cause`, `turning_point_signal`, `why_symptoms_misleading`, `escalation_rule`, `delay_risk` (and related). No repair steps or command sequences stored.
- **Audit trail**
  - QARecord per question/answer; Incident.full_state; escalation objects with timestamps, reasons, level. No code changes; compliance confirmed.

---

## 7. Optional UX / Hardening

- **Unsafe options**
  - Options that violate safety (high risk when blocks exist) are marked `blocked_by_safety=True` and non-recommended; at least one non-blocked option is recommended when possible.
- **Escalation visibility**
  - Failure paths, verification failure, and programmatic triggers already set `escalation_triggered` and `escalation_reasons`; no change.
- **Pydantic**
  - Decision brief options are validated with `DecisionOption`; brief with `DecisionBrief`. Hypothesis with `Hypothesis` (including `root_cause_layer`).

---

## Files Touched

| File | Changes |
|------|--------|
| `src/sanitization.py` | **New**: forbidden phrases, `sanitize_decision_brief()` |
| `src/state/state.py` | `DecisionOption.blocked_by_safety`; `Hypothesis.root_cause_layer` default `"symptom"` |
| `src/agents/decision_brief_agent.py` | Sanitization call; safety blocking; comments |
| `src/agents/hypothesis_agent.py` | Enforce `root_cause_layer` default "symptom" and valid values |
| `api.py` | `_load_state(incident_id, company_id)`; all incident routes pass `user.company_id` → 404 for wrong tenant |
| `src/agents/safety_agent.py` | Docstring: programmatic escalation list |
| `src/agents/expert_capture_agent.py` | Docstring: boundary and stored fields |
| `src/agents/memory_write_agent.py` | Docstring: boundary and tenant |
| `src/agents/escalation_agent.py` | Docstring: boundary and tenant |
| `src/agents/question_agent.py` | Comment: deduplication and context-aware narrowing |

All changes are backward-compatible with the MVP and preserve the human-in-the-loop decision workflow.
