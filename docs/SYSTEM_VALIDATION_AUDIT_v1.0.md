# Decisio v1.0 — Full System Validation Audit

**Role:** Senior Industrial QA & Governance Auditor  
**Scope:** Decision Leadership Platform (not maintenance/automation tool)  
**Date:** 2025-02-24  
**Version:** 1.0

---

## Executive Summary

This audit validates Decisio v1.0 against its design philosophy: **decision options only, no execution guidance; safety as constraints; root cause isolation; human-in-the-loop**. The codebase was reviewed for boundary compliance, multi-tenant isolation, safety enforcement, escalation logic, decision memory integrity, and governance.

**Critical issues identified in code have been remediated** (multi-tenant data layer and Decision Memory scoping). Remaining findings and scores are below.

---

## 1. Boundary & Role Validation (Critical)

### Design Requirements

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Never provides repair steps | ✅ Enforced in prompts | `decision_brief_agent.py`: CRITICAL BOUNDARY in SYSTEM_PROMPT — "Never include: Repair steps, Disassembly instructions, Command sequences, Operational execution steps". Same in `expert_capture_agent.py`, `memory_write_agent.py`, `escalation_agent.py`. |
| Never issues operational commands | ✅ Prompt-level | Decision Brief prompt: "You provide DECISION OPTIONS only — what to decide, not how to execute." |
| Never suggests control system changes | ✅ Prompt-level | Same boundary; options are decision-level (e.g. "Decide to recalibrate" not "Set setpoint to X"). |
| Never bypasses safety constraints | ✅ Programmatic + prompt | Safety blocks force `requires_escalation`; programmatic checks in `safety_agent.py` (risk ≥ 8, blocks, contradictions). |
| Never replaces human decision authority | ✅ By design | Brief presents options + decision_authority + escalation_path; human chooses and executes. |
| Always presents decision options (not instructions) | ✅ | DecisionOption model: title, description, risks, constraints; no step-by-step. |
| Always includes safety constraints | ✅ | Brief merges `safety_constraints` into context and into each option; `safety_blocks` in context. |
| Human-in-the-Loop | ✅ | Workflow stops at Brief; outcome/verify submitted by user; no auto-execution. |

### Gaps / Risks

- **No programmatic output sanitization.** Decision Brief and other agent outputs are not scanned for forbidden phrases (e.g. "step 1:", "setpoint", "disassemble"). Compliance relies entirely on LLM prompts. A misbehaving or over-helpful model could still emit execution guidance.
- **Recommendation:** Add a lightweight post-check (keyword blocklist or classifier) on `options[].description` and `analysis_summary`; reject or redact if execution language detected. **Severity: Medium** (Safety / Decision Logic).

**Verdict:** Boundary is **correctly specified and consistently prompted**. No CRITICAL BUG found where execution guidance is intentionally produced. Risk is **prompt bypass only**.

---

## 2. Webchat Workflow Testing (MVP Flow)

### Lifecycle: Report → Classify → Question → Analyze → Decision Brief → Outcome → Memory

| Stage | Implementation | Notes |
|-------|----------------|------|
| Report | `incident_intake_agent` | Free-text → Incident Card (normalized_summary, asset_id, symptoms, severity, safety_level). |
| Classify | `screening_agent` | Severity, safety_level, impact, scope, initial_risk_score, process_failure_suspected, gating_flags. Immediate escalation if danger or risk ≥ 8. |
| Question | `question_agent` | 3 questions per diagnostic step; 10-step framework; process/human questions when process_failure_suspected or step 1–3. |
| Analyze | `answer_interpreter` → `hypothesis_update` → `safety_constraint` → `advance_step` | Facts, hypotheses, confidence, risk, safety blocks. |
| Decision Brief | `decision_brief_agent` | 2–4 options, risks, constraints, escalation guidance, one-screen format. |
| Outcome | `outcome_capture_agent` | success/failure/partial; AWAITING_VERIFICATION on success until verify. |
| Memory | `memory_write_agent` | On success + verification; stores decision pattern with company_id. |

### Validation Points

- **Incident Card creation:** ✅ After intake + screening.
- **2–3 screening pre-classification questions:** ⚠️ No separate user-facing "screening questions"; screening is LLM classification. First **diagnostic** batch is 3 questions (step 1: Trigger Condition). If spec meant "2–3 questions before full diagnosis", current flow has 3.
- **Dynamic diagnostic questions:** ✅ By step and Q&A history; deduplication in `question_agent`.
- **No redundant questions:** ✅ Dedup in `_is_duplicate` and "do not repeat" in prompt.
- **Context-aware narrowing:** ✅ Step advancement and hypothesis-driven context.
- **Decision Brief one-screen format:** ✅ Single JSON with options, risk_summary, escalation_guidance.
- **Safety constraints visible:** ✅ In context and in brief; safety_blocks in context.
- **Escalation triggers:** ✅ Programmatic (risk, blocks, contradictions, budget) and pattern-based.
- **Closure verification rule:** ✅ `outcome_capture_agent` sets `AWAITING_VERIFICATION` on success; API `/verify` required before CLOSED; verification_confirmed and notes stored.

### Test Scenarios (Design Coverage)

- **Clear technical failure:** Hypothesis + questions cover internal_equipment, instrumentation, etc.; brief can recommend e.g. "Decide to isolate and inspect".
- **Hidden process failure:** Screening sets `process_failure_suspected`; question agent adds procedure_human questions; hypothesis agent treats process as first-class.
- **Conflicting signals:** Contradictions list; confidence drop; ≥3 contradictions trigger escalation.
- **No alarm case:** Handled by trigger_condition step and process_failure indicators.
- **Recurring failure:** Retrieval agent recurrence detection (same asset + high similarity); risk bump and optional auto-escalation.

**Verdict:** MVP flow is **implemented and coherent**. Minor gap: explicit "2–3 screening questions" as user-facing Q&A is not present (classification is automated).

---

## 3. Root Cause Isolation Framework Validation

### 10 Fixed Categories

All 10 categories are defined in `state.py` (`DIAGNOSTIC_CATEGORIES`) and in `question_agent.py` SYSTEM_PROMPT:

1. Trigger Condition  
2. Internal Equipment  
3. Upstream Equipment  
4. Downstream Equipment  
5. Control System  
6. Instrumentation  
7. Utilities  
8. Process Conditions  
9. Procedure/Human  
10. Verification & Closure  

### Behaviour

- **Trigger vs symptom:** Hypothesis agent uses `root_cause_layer`: symptom / trigger / root_cause. Decision brief agent receives "symptom_only" check: if all hypotheses are symptom-level, context adds "Root cause is NOT isolated" and "Do NOT recommend internal machine actions."
- **Avoid reacting to symptom only:** Enforced by symptom_only branch and prompt.
- **Process failures early:** Screening sets process_failure_suspected; question agent injects procedure_human questions in steps 1–3 when suspected.
- **Premature restart:** Prompt forbids recommending internal machine actions before isolating trigger; symptom_only path reinforces this.

**Risk:** If the hypothesis agent does not set `root_cause_layer` on hypotheses, the symptom_only check (`all(h.get("root_cause_layer") == "symptom")`) can be false (e.g. default "root_cause"), and the "further diagnosis" warning may not appear. **Recommendation:** Ensure every hypothesis has `root_cause_layer` set; default to "symptom" when uncertain. **Severity: Medium** (Decision Logic).

**Verdict:** Framework is **correct and used**. Isolation quality depends on hypothesis layer accuracy; no code path was found that "jumps to a fix without isolation" except via LLM drift (mitigated by prompt and symptom_only).

---

## 4. Process Failure Detection Stress Test

- **Incomplete shift handover / missed manual verification / conflicting SOP / undocumented approval / batch change without procedure update:** Screening prompt (§8) and `process_failure_indicators` target these; question agent adds procedure_human questions; hypothesis agent ranks process hypotheses.
- **Process failure as first-class:** ✅ Screening, questions, and hypotheses all treat it as first-class.
- **No blaming language:** Prompt does not prescribe "blame"; descriptions are neutral (e.g. "procedure missed").
- **Procedural correction as decision option:** Handled by LLM generating options (e.g. "Decide to update procedure and re-verify handover").
- **Escalation:** Failed attempts, low confidence, and safety triggers all feed escalation.

**Verdict:** Process failure detection is **designed and wired**; stress behaviour depends on LLM quality and data (e.g. incident text mentioning handover).

---

## 5. Safety Constraint Enforcement

- **Rising pressure / overheating / partial cooling / repeated failure / technician inability:** Safety agent uses equipment rules from DB, risk score, failed attempts, contradictions; programmatic escalation (risk ≥ 8, safety blocks, contradiction count).
- **Tightening after failure:** Outcome capture adds safety_tightening and risk_adjustment; safety agent prompt asks for risk_adjustment per failed attempt.
- **Blocking unsafe options:** Options are generated with risks and constraints; there is no programmatic removal of "high" risk options from the brief — they remain visible with explicit risk. Design is "constraint visibility" not "hide dangerous option". **Recommendation:** Consider marking options that violate active safety_blocks as non-recommended and clearly blocked in UI. **Severity: Low** (UX/Safety).
- **Mandatory escalation:** Safety blocks and risk threshold force escalation in code.
- **No "be careful" only:** Prompts ask for constraints/blocks, not soft advice.
- **Expert does not override constraints:** Expert capture and escalation handoff do not clear safety_blocks or lower risk programmatically.

**Verdict:** Safety enforcement is **strong** (programmatic + DB rules + prompts). No CRITICAL finding where an unsafe decision is explicitly recommended without constraints; high-risk options are labelled.

---

## 6. Escalation Logic Testing

- **Triggers:** Failed path, high risk, conflicting signals, repeated incident, technician inability (via outcome/failure), mandatory pattern, verification failure.
- **Level chosen:** `_determine_escalation_level` uses safety_level, safety_blocks, DB rules, risk, contradictions, failed_attempts, severity, must_escalate patterns. Levels are now **tenant-scoped** (company_id passed to get_escalation_levels / get_escalation_rules).
- **Context package:** Escalation agent builds handoff with incident, Q&A, facts, hypotheses, constraints, blocks, decision options, escalation reasons.
- **Unnecessary/delayed escalation:** Logic is threshold-based; no finding of deliberate delay. High risk and safety blocks escalate immediately.

**Verdict:** Escalation logic is **correct and tenant-aware** after fixes.

---

## 7. Decision Memory & Knowledge Capture

- **After expert resolution:** outcome_capture stores root_cause_confirmed, turning_point_signal; memory_write and expert_capture store patterns with title, signals, decision_taken, must_escalate, root_cause, turning_point_signal, why_symptoms_misleading, escalation_rule, delay_risk, etc.
- **Does NOT capture:** Repair steps, disassembly, setpoints, execution details — stated in prompts and in memory_write/expert_capture design.
- **Similar incident recurrence:** Retrieval is company-scoped; similar incidents improve context for questions and hypotheses. Pattern is scoped per tenant via `company_id` in payload and filter.

**Verdict:** Memory design is **compliant**; expert_capture now writes `company_id` so patterns are tenant-isolated.

---

## 8. Multi-Tenant Isolation (Critical for SaaS)

### Findings and Fixes Applied

| Issue | Severity | Fix |
|-------|----------|-----|
| Safety rules fetched without company_id | **Critical** | `get_all_applicable_rules(equipment_type, severity, company_id=company_id)`; safety_agent passes state company_id. |
| Escalation levels/rules without company_id | **Critical** | `get_escalation_levels(company_id)` and `get_escalation_rules(company_id)`; escalation_agent passes company_id. |
| Equipment lookup without company_id | **Critical** | `get_asset(asset_id, company_id=company_id)` and get_asset_type; screening_agent and escalation_agent pass company_id. |
| Retrieval when company_id missing | **High** | retrieval_agent now returns empty patterns when company_id is None (no cross-tenant leak). |
| Expert capture pattern without company_id | **Critical** | expert_capture_agent now sets `company_id` in pattern payload for Qdrant. |

### API and DB

- **Incident access:** All incident endpoints check `state["company_id"] == user.company_id`; 403 if not. List incidents uses `company_id=user.company_id`. Create incident sets `state["company_id"] = user.company_id`.
- **CRUD:** create_incident / update_incident use state company_id; get_incident(session, incident_id, company_id) is available; API currently loads by ID then checks company (403 for wrong tenant). **Recommendation:** Call get_incident with user.company_id so wrong-tenant ID returns 404. **Severity: Low** (Isolation / UX).
- **Vector search:** Filter `company_id` applied when company_id is present; when None, retrieval now returns empty (no search).

**Verdict:** Multi-tenant isolation is **enforced at API and data layer** after the applied code changes. No CRITICAL open issue.

---

## 9. RAG & Pattern Retrieval Validation

- **Embedding metadata:** Stored patterns include `company_id` (memory_write_agent, expert_capture_agent).
- **Retrieval scoped per tenant:** Qdrant filter `company_id`; when company_id is None, retrieval returns no patterns.
- **No hallucinated patterns:** Only Qdrant hits above MIN_SIMILARITY_THRESHOLD are returned; no synthetic patterns injected.
- **Fallback when no similar pattern:** Empty list; downstream uses LLM-only reasoning.
- **Confidence boundaries:** retrieval_confidence from average similarity; used in state.

**Verdict:** RAG is **tenant-scoped and safe**; no fabrication of patterns.

---

## 10. Governance & Auditability

- **Audit trail:** Q&A stored in DB (QARecord per question/answer); outcome records; incident state (including decision_brief, escalation, verification). Full state snapshot in Incident.full_state.
- **Questions/answers/options/constraints:** Present in state and in escalation handoff.
- **Escalation timing:** Escalation object has timestamp; reasons and level stored.
- **Incident not closable without verification:** Success → AWAITING_VERIFICATION; CLOSED only after POST /verify with trigger_normalized true.
- **Decision authority level:** decision_authority and escalation_path in brief.

**Verdict:** Governance and auditability are **supported** by state and DB design.

---

## 11. Performance Validation (MVP KPI)

- **<2 s average response time:** Not measured in this audit; depends on LLM and infra. No obvious synchronous blocking beyond LLM calls.
- **Stable WebSocket chat:** API is REST; no WebSocket implementation found. If frontend uses polling or future WebSocket, stability is out of scope of this code audit.
- **Concurrent incidents:** Stateless graph; company_id and incident_id scope state; no global mutable state for decisions.
- **No memory corruption:** State is merged by LangGraph; no finding of shared mutable corruption.
- **Decision generation stability:** JSON fallbacks in agents; validated with Pydantic where used.

**Verdict:** No structural performance or stability bugs identified; KPIs require load testing and monitoring.

---

## 12. Bug Reporting Format — Summary of Issues

### Critical (Remediated in Code)

- **Safety rules / escalation / equipment not tenant-scoped:** Agents now pass `company_id` to safety_rules, escalation_matrix, and assets. **Fixed.**
- **Expert capture patterns stored without company_id:** Pattern payload now includes `company_id`. **Fixed.**
- **Retrieval without company_id could leak cross-tenant:** When company_id is None, retrieval returns empty patterns. **Fixed.**

### High

- None remaining after fixes.

### Medium

- **Decision Brief output not sanitized:** No programmatic check for execution language; prompt-only. **Category:** Safety / Decision Logic. **Recommendation:** Add post-generation check (blocklist or classifier) on option descriptions and analysis_summary.
- **Hypothesis root_cause_layer default:** If hypotheses lack `root_cause_layer`, symptom_only check may not trigger. **Category:** Decision Logic. **Recommendation:** Ensure all hypotheses have root_cause_layer; default to "symptom" when unclear.

### Low

- **get_incident without company_id:** API could return 404 for wrong-tenant incident (by passing user.company_id to get_incident) instead of 403. **Category:** Isolation / UX.
- **Options violating safety_blocks:** No automatic marking of options as blocked when they conflict with safety_blocks. **Category:** UX / Safety.

---

## Final Deliverables

### Scores (0–10)

| Score | Value | Rationale |
|-------|--------|-----------|
| **Decision Quality** | 8 | 10-step framework, symptom/trigger/root_cause, process first-class; quality depends on LLM and hypothesis layers. |
| **Safety Enforcement** | 8 | Programmatic escalation and blocks; equipment rules; no programmatic stripping of unsafe options. |
| **Escalation Logic** | 9 | Clear triggers, level routing, context package, tenant-scoped after fix. |
| **Multi-Tenant Isolation** | 9 | API and DB scoped; retrieval and memory fixed; get_incident 404 improvement optional. |
| **RAG Reliability** | 8 | Tenant filter, no fabrication, fallback to LLM-only; confidence threshold. |
| **Governance Compliance** | 8 | Audit trail in DB and state; verification gate; decision authority in brief. |

### Production Readiness Assessment

- **Philosophy alignment:** Decisio respects decision-only boundary, safety-as-constraint, root cause discipline, and human-in-the-loop in design and prompts.
- **Critical blockers:** **None** after the multi-tenant and memory fixes applied.
- **Before production:** (1) Add optional output sanitization for decision brief. (2) Ensure hypothesis agents always set root_cause_layer. (3) Load-test for <2 s and concurrency. (4) Prefer get_incident with company_id for 404 on wrong tenant.

### Mission Outcome

- **Break decision logic:** Logic holds under review; symptom_only and prompts reduce risk of acting on symptom only.
- **Test boundaries:** Boundaries are explicit in prompts; no code path intentionally emits repair steps or commands.
- **Force unsafe output:** Safety blocks and escalation cannot be overridden by expert path; no CRITICAL unsafe-decision path found.
- **Force cross-tenant leakage:** Leakage from safety/escalation/equipment and from Decision Memory was found and **fixed**; retrieval when company_id missing now returns empty.
- **Force premature execution advice:** Prompt and symptom_only path discourage it; no programmatic enforcement that strips such content.

**Conclusion:** With the critical multi-tenant and Decision Memory fixes applied, Decisio v1.0 is **MVP-ready** from a boundary, safety, isolation, and governance perspective, subject to the recommended hardening (output check, root_cause_layer, and performance validation).
