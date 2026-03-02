# Decisio — Task Tickets

Based on [Decisio Draft English Translation](file:///home/code/Decisio/_MConverter.eu_Decisio_Draft_English_Translation.md)

---

## TICKET-01: Escalation Agent — Expert Handoff Package
**Priority:** P1 | **Section:** §10  
**Description:** Build the Escalation Agent that creates a full-context handoff package when escalation is triggered. Package includes: incident report, Q&A timeline, what was tried and failed, decision options presented, current safety constraints, and hypotheses. Route to the correct escalation level (line supervisor → specialist → internal expert → OEM → admin shutdown).  
**Acceptance:** Agent generates a structured escalation document with full incident context and correct routing level.

---

## TICKET-02: Escalation Level Routing Logic
**Priority:** P1 | **Section:** §10  
**Description:** Implement escalation level classification: (1) Line supervisor for moderate severity, (2) Specialized maintenance team, (3) Internal expert, (4) OEM/manufacturer for rare/high-risk, (5) Administrative escalation for shutdown. Routing should be based on severity, failed attempts, risk score, and pattern match.  
**Acceptance:** Escalation routes to the correct level based on state inputs.

---

## TICKET-03: Expert Knowledge Capture Flow
**Priority:** P1 | **Section:** §11  
**Description:** After an expert resolves an incident, build an interactive capture flow that records: the signal that confirmed the cause, why symptoms were misleading, why first-line attempts failed, the turning-point decision, when escalation should happen in the future, and risk of delaying. Must NOT capture: repair steps, operating instructions, setpoints.  
**Acceptance:** Expert input is captured and stored as a decision pattern in Qdrant.

---

## TICKET-04: Outcome Loop — Retry on Failure
**Priority:** P1 | **Section:** §5 Step 7, §9  
**Description:** When the operator reports failure, the system should tighten safety constraints, increment risk, and either (a) loop back to diagnosis with tighter constraints, or (b) trigger escalation if 2+ attempts failed. Wire this into the LangGraph graph as a conditional edge from outcome_capture back to question_generation or escalation.  
**Acceptance:** Failed outcome loops back to diagnosis with tightened constraints; 2+ failures force escalation.

---

## TICKET-05: Verification & Closure Gate (Step 10)
**Priority:** P1 | **Section:** §13  
**Description:** An incident is NOT resolved until: trigger conditions normalize, verification steps are completed and recorded. Build a verification gate node that checks these conditions before allowing closure. Step 10 questions should explicitly ask for normalization confirmation.  
**Acceptance:** Incidents cannot be closed until trigger normalization is confirmed.

---

## TICKET-06: Fast Pre-Classification Path
**Priority:** P2 | **Section:** §14 MVP  
**Description:** Implement a fast screening path with 2-3 human-readable classification questions (impact, scope, safety level) before the full LLM-based screening runs. This gives immediate routing for obvious cases.  
**Acceptance:** Simple incidents classify in under 2 seconds without LLM call.

---

## TICKET-07: Category-Driven Question Bundling
**Priority:** P2 | **Section:** §14 MVP  
**Description:** Group diagnostic questions by category so the operator answers related questions together instead of one at a time. The Question Agent should generate a bundle of 3 questions per step, and the operator can answer all at once.  
**Acceptance:** Questions are presented as grouped bundles per diagnostic step.

---

## TICKET-08: FastAPI REST Endpoints
**Priority:** P2 | **Section:** §24  
**Description:** Build the FastAPI backend with REST endpoints: POST /incidents (create incident), POST /incidents/{id}/messages (send answer), GET /incidents/{id}/brief (get decision brief), POST /incidents/{id}/escalate (manual escalation), GET /incidents/{id}/status (get current state).  
**Acceptance:** All endpoints return correct data and work with the LangGraph pipeline.

---

## TICKET-09: WebSocket Real-Time Chat
**Priority:** P2 | **Section:** §24, §2.4  
**Description:** Add WebSocket endpoint for real-time Webchat. The operator sends messages and receives questions/briefs in real-time. State updates stream to the client as the diagnosis progresses.  
**Acceptance:** WebSocket connection maintains session and streams agent responses.

---

## TICKET-10: PostgreSQL Persistent Storage
**Priority:** P2 | **Section:** §24  
**Description:** Set up PostgreSQL schema for: incidents, incident_cards, qa_history, decision_briefs, escalation_cases, audit_events. Replace in-memory state with database persistence so incidents survive restarts.  
**Acceptance:** All incident data persists across server restarts.

---

## TICKET-11: React Webchat UI
**Priority:** P2 | **Section:** §13, §14 MVP  
**Description:** Build a React + TypeScript Webchat interface with: incident report input, guided Q&A chat flow, decision brief display (one-screen output per §14), safety constraint warnings, escalation status display, and incident history list.  
**Acceptance:** Operator can complete full incident flow through the web UI.

---

## TICKET-12: Decision Brief One-Screen Output
**Priority:** P2 | **Section:** §14 MVP, §19.3  
**Description:** Format the Decision Brief into a single-screen summary following the template in §19.3: analysis summary, root cause hypothesis, decision options (RECOMMENDED / NOT RECOMMENDED), safety constraints, decision authority level, and escalation path.  
**Acceptance:** Brief fits on one screen and matches the template format.

---

## TICKET-13: Tenant Isolation
**Priority:** P2 | **Section:** §13, §24  
**Description:** Implement tenant isolation for multi-customer deployment: separate Qdrant namespaces per tenant, tenant-scoped database queries, tenant ID in all API requests, and data separation validation.  
**Acceptance:** Tenant A cannot see or search Tenant B's data.

---

## TICKET-14: Audit Trail & Decision Documentation
**Priority:** P2 | **Section:** §13  
**Description:** Build an immutable audit log that records every decision step: who reported, what questions were asked, what answers were given, what options were presented, what was chosen, and the outcome. This satisfies the "full auditability" requirement.  
**Acceptance:** Every incident has a complete, immutable audit trail.

---

## TICKET-15: Process Failure Detection Enhancement
**Priority:** P2 | **Section:** §8  
**Description:** Enhance process failure detection beyond screening: track process-failure-specific hypothesis category through the full loop, add dedicated process failure questions when signals appear mid-diagnosis (not just at screening), and include process failure rate in analytics.  
**Acceptance:** Process failures are detected and tracked as first-class root causes throughout the loop.

---

## TICKET-16: Safety Constraint Tightening on Recurrence
**Priority:** P2 | **Section:** §9  
**Description:** When the same failure recurs in a short time window (same asset, similar symptoms), automatically tighten safety constraints and increase the starting risk score. Pull recurrence data from Decision Memory.  
**Acceptance:** Recurring incidents start with higher risk and tighter constraints.

---

## TICKET-17: Read-Only System Integrations
**Priority:** P3 | **Section:** §6, §13  
**Description:** Build optional read-only connectors for SCADA/monitoring/alarm/CMMS systems to verify operator-reported data. Integrations are verification-only — no write, no control, no commands.  
**Acceptance:** System can pull live readings to validate against operator answers.

---

## TICKET-18: Authentication & RBAC
**Priority:** P3 | **Section:** §24  
**Description:** Integrate Auth0 or Keycloak for SSO. Implement role-based access: Operator (report + answer), Supervisor (view briefs + approve escalation), Expert (resolve + capture knowledge), Admin (full access + config).  
**Acceptance:** Users authenticate via SSO and see only role-appropriate features.

---

## TICKET-19: Integration & Load Testing
**Priority:** P2 | **Section:** §27  
**Description:** Build end-to-end integration tests: full 10-step diagnostic flow, escalation flow, outcome capture + memory write, multi-incident concurrent handling. Load test: API rate limiting, LLM failure handling with retry logic, response time < 2 seconds target.  
**Acceptance:** All tests pass; response time meets KPI target.

---

## TICKET-20: Deployment & Observability
**Priority:** P2 | **Section:** §24, §27  
**Description:** Set up Docker containers for all services (API, LangGraph workers, Qdrant, Postgres). Add monitoring, logging, and alerting. Create environment configs for dev/staging/prod. Write deployment runbook, operator guide, and API documentation. Target uptime > 99.5%.  
**Acceptance:** System deploys via Docker Compose, dashboards show health metrics, docs are complete.

---

## Summary

| Priority | Count | Tickets |
|----------|-------|---------|
| P1 | 5 | #01, #02, #03, #04, #05 |
| P2 | 11 | #06–#16, #19, #20 |
| P3 | 2 | #17, #18 |
