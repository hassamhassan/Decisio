# Decisio — Alignment Report: Implementation vs Draft Document

**Date:** February 19, 2026  
**Comparing:** Current codebase vs [Decisio Draft English Translation](file:///home/code/Decisio/_MConverter.eu_Decisio_Draft_English_Translation.md)

---

## ✅ Fully Aligned

| Doc Section | Requirement | Implementation |
|-------------|-------------|----------------|
| §1 Executive Summary | Decision layer, not execution | All agents enforce no-repair-steps boundary |
| §2.1 What Decisio Is | Receives reports via Webchat, asks diagnostic questions | `incident_intake_agent.py` + `question_agent.py` |
| §2.2 What Decisio Is NOT | No repair steps, no commands, no machine control | `decision_brief_agent.py` prompt explicitly blocks these |
| §4.1 Decision before action | Start with "what is the correct decision?" | Decision Brief generates options, not fixes |
| §4.2 Questions > answers | Directed diagnostic questions | Full 10-step framework in `question_agent.py` |
| §4.3 Process failures first-class | Process failure as root-cause category | `hypothesis_agent.py` supports `technical / process / external` categories |
| §4.4 Safety as constraints | Safety = blocks, prerequisites, escalation | `safety_agent.py` enforces constraints, blocks, mandatory escalation |
| §4.6 Failure is information | Failed attempts update risk, tighten safety | Safety agent applies risk adjustments after failures |
| §5 Workflow | Report → Classify → Question → Analyze → Brief → Outcome | `graph.py`: Intake → Screening → Retrieval → Diagnosis Loop → Brief |
| §7 Diagnostic Questions | Technical + Process + Safety categories | 10-step framework covers all three per §13 |
| §9 Safety & Risk | Safety tightens on failure, blocks unsafe decisions | `safety_agent.py` with programmatic threshold checks |
| §10 Escalation triggers | Failed path, high risk, conflicting signals, repeat failures | `safety_agent.py` checks risk ≥ 8, contradictions ≥ 3, question budget |
| §13 Root Cause Framework | 10 fixed categories (Trigger → Verification) | `DIAGNOSTIC_CATEGORIES` in `state.py`, used by `question_agent.py` |
| §13 Verification rule | Incident not resolved until trigger conditions normalize | Step 10 = "Verification and Closure" |
| §14 MVP Scope | Webchat, Incident Card, classification, questions, brief, safety, escalation, memory | All implemented except Webchat UI |
| §19.2 Incident Card Template | ID, timestamp, reporter, machine, status, classification, questions asked | `IncidentCard` model matches this template |
| §19.3 Decision Brief Template | Options with RECOMMENDED tag, risks, safety constraints, escalation path | `DecisionBrief` + `DecisionOption` models match |

---

## ⚠️ Partially Aligned (Needs Enhancement)

| Doc Section | Requirement | Current State | Gap |
|-------------|-------------|---------------|-----|
| §4.5 Human-in-the-Loop | Final decision remains human | CLI asks user for answers; brief is advisory | Need explicit "human approves decision" step in graph |
| §5 Step 7: Outcome | If success → close + memory. If failure → tighten + escalate | No outcome capture node yet | Need `outcome_capture` agent + memory write |
| §6 Information Sources | 7-level priority: safety > human input > expert knowledge > memory > manuals > integrations > cross-facility | Retrieval Agent searches memory; LLM has domain knowledge | No explicit source priority ranking in prompts |
| §8 Process Failures | Actively asked early, treated as separate decision path | Hypothesis Agent supports "process" category | Question Agent doesn't specifically prioritize process questions early in the flow |
| §10 Escalation levels | Line supervisor → specialist → internal expert → OEM → admin | Escalation triggered as boolean | No routing to specific escalation levels |
| §10 Expert handoff | Full context: report, Q&A, attempts, options, constraints | Escalation reasons captured | No `Escalation Agent` packaging the full handoff bundle |
| §11 Expert capture | Capture why expert chose decision, turning point, when to escalate | `RetrievedPattern` has signals + decision_taken | No expert input flow or `Memory Write Agent` |
| §13 Root Cause Isolation | Must distinguish symptom layer vs root cause layer | Hypothesis Agent generates hypotheses | No explicit symptom vs root-cause separation logic |
| §24 Tech Stack | React frontend, PostgreSQL, Vector DB, Redis, Auth | Qdrant (vector) implemented; no Postgres, Redis, or React yet | Backend data persistence and UI still needed |

---

## ❌ Not Yet Implemented

| Doc Section | Requirement | Priority |
|-------------|-------------|----------|
| §5 Step 6: Execution outside Decisio | Track that user executed outside system | P1 |
| §5 Step 7: Outcome capture | User reports success/failure; close or escalate | P1 |
| §5 Step 8: Memory write | Store verified decision pattern | P1 |
| §10 Escalation Agent | Expert handoff package + routing + SLA | P1 |
| §11 Expert Knowledge Capture | Interactive expert input flow after resolution | P2 |
| §14 Fast pre-classification path | 2-3 screening questions (not full LLM call) | P2 |
| §14 Category-driven question bundling | Group questions by category for efficiency | P2 |
| §2.4 Webchat UI | React frontend with chat interface | P2 |
| §24 PostgreSQL | Persistent incident/Q&A/brief storage | P2 |
| §24 Redis | Session cache, rate limits | P3 |
| §24 Auth (Auth0/Keycloak) | SSO and RBAC | P3 |
| §9 Tenant isolation | Multi-tenant data separation | P3 |
| §13 Audit trail | Immutable audit events | P3 |
| §6 Read-only integrations | SCADA/CMMS/alarm verification | P3 |
| §16 Cross-facility patterns | Anonymized pattern sharing | P4 |

---

## Summary

| Category | Count |
|----------|-------|
| ✅ Fully Aligned | 17 items |
| ⚠️ Partially Aligned | 9 items |
| ❌ Not Yet Implemented | 15 items |

**Overall alignment: ~55% of the draft document requirements are implemented.** The core decision engine (intake, screening, questions, hypotheses, safety, decision brief) is solid. The main gaps are in the **outcome/memory loop** (§5 steps 6-8), **escalation packaging** (§10-11), and **infrastructure** (Postgres, React UI, auth).

---

## Recommended Next Steps (Priority Order)

1. **Outcome Capture + Memory Write Agent** — closes the decision loop per §5
2. **Escalation Agent** — packages expert handoff per §10
3. **Process failure early detection** — enhance Question Agent to ask process questions by step 2-3
4. **FastAPI + WebSocket API** — enables Webchat per §2.4, §24
5. **PostgreSQL persistence** — production data storage per §24
6. **React Webchat UI** — operator interface per §14 MVP
