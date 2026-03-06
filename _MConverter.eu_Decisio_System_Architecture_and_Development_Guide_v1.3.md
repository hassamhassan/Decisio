# 1. Executive Summary {#executive-summary}

Decisio is an operational decision-support system designed to lead decisions during complex operational failures. It receives incident reports through a webchat interface, asks guided diagnostic questions, and produces a Decision Brief that contains decision options, risk notes, safety constraints, and escalation guidance. Decisio is explicitly not a maintenance management system and does not execute operational commands or repair steps.

This document explains the complete development scope and technical architecture, including user input flow, LangGraph orchestration, escalation node activation, and detailed agent responsibilities.

## 1.1 What Decisio Is / Is Not {#what-decisio-is-is-not}

- A decision layer: diagnosis guidance, decision options, constraints, escalation leadership.

- Not an execution layer: it does not issue commands, repairs, configuration changes, or operational sequences.

- Integrations are optional and read-only, used only for verification and context.

- All decisions remain human-approved; the system provides structured support and auditability.

# 2. Product Scope and Core Concepts {#product-scope-and-core-concepts}

## 2.1 Core Entities {#core-entities}

|                           |                                                 |                                                                    |
|---------------------------|-------------------------------------------------|--------------------------------------------------------------------|
| **Entity**                | **Purpose**                                     | **Key Fields (examples)**                                          |
| Incident                  | A single operational failure case               | id, tenant_id, timestamp, asset_id, status, severity, safety_level |
| Incident Card             | Structured summary used throughout the workflow | report, classification, Q&A history, attempts, decisions           |
| Diagnostic Question       | Reduce uncertainty                              | category, rationale, expected_answer_type, blocking_safety_flag    |
| Decision Brief            | Outcome artifact                                | options, risks, constraints, escalation, confidence                |
| Decision Pattern (Memory) | Reusable, verified decision logic               | signals, question-path, triggers, escalation rules                 |
| Escalation Case           | Expert handoff bundle                           | package, routing, SLA, expert notes, closure reasoning             |

# 3. End-to-End Workflow (Webchat) {#end-to-end-workflow-webchat}

1.  Report: user starts a webchat incident and submits the initial description and optional attachments.

2.  Screening: system assigns impact, scope, and safety posture using a short screening path.

3.  Diagnosis loop: system asks targeted diagnostic questions (technical, process, safety).

4.  Analysis: decision engine updates hypotheses, confidence, and risk after each answer.

5.  Decision Brief: system generates multiple decision options with risks and safety constraints (no repair steps).

6.  Execution outside Decisio: user executes the chosen option outside the platform.

7.  Outcome capture: user reports success/failure; system either closes or escalates.

8.  Decision Memory: verified patterns and expert reasoning are stored for future retrieval.

## 3.1 When Escalation is Called {#when-escalation-is-called}

Escalation is a router decision in the LangGraph workflow. The Escalation node is activated when one or more conditions below are true. Each activation must be logged with the exact trigger(s), evidence, current risk score, confidence, and the incident state snapshot.

Escalation can be automatic (policy/risk driven) or manual (user request).

### 3.1.1 Escalation Trigger Conditions {#escalation-trigger-conditions}

- Safety red-line triggered (hard stop): safety unknown, hazard present, permit/approval missing, or policy blocks any further first-line attempts.

- Risk score \>= escalation_threshold for this incident class (severity × safety × uncertainty).

- Confidence remains below confidence_threshold after question_limit is reached (question budget exhausted).

- Attempt count \>= attempt_limit (recommended decision options tried and failed).

- Contradictions detected (answer conflicts that prevent stable hypotheses).

- Repeat incident detected for same asset/symptom cluster within recurrence_window.

- Mandatory escalation pattern matched from Decision Memory (pattern includes \'must_escalate\').

- User explicitly requests escalation at any point.

### 3.1.2 Escalation Router Priority (Recommended) {#escalation-router-priority-recommended}

9.  Safety blocks (red-line)

10. Mandatory escalation patterns (from memory)

11. Risk threshold

12. Attempt budget

13. Low confidence after question budget

14. Contradictions / recurrence

15. User request

### 3.1.3 What Happens Immediately After Escalation is Called {#what-happens-immediately-after-escalation-is-called}

16. Freeze the current Decision Brief version and mark it as \'Last First-Line Brief\'.

17. Create an Escalation Case record (level, routed_to, SLA timers, status).

18. Build the Expert Handoff Package: incident summary, classification, full Q&A, attempts, hypotheses, constraints, attachments, and optional read-only snapshots.

19. Notify the routed group (supervisor, maintenance specialists, internal expert, OEM).

20. Switch the incident state to ESCALATED and continue interaction under expert mode (still audited).

21. On closure, capture expert reasoning into Decision Memory (pattern + escalation rules) without storing repair steps.

## 3.2 Architecture Diagram {#architecture-diagram}

Agent architecture diagram showing every agent and the iterative question loop (no audit/verify nodes).

![](media/image1.png){width="6.720138888888889in" height="5.84375in"}

*Figure 1: Decisio agents and question loop with escalation activation.*

# 4. System Architecture (Production) {#system-architecture-production}

## 4.1 Component Overview {#component-overview}

|                        |                                                                                        |
|------------------------|----------------------------------------------------------------------------------------|
| Webchat UI             | Incident reporting, guided Q&A, Decision Brief viewing, attachments.                   |
| API Gateway            | Auth, tenant routing, rate limiting, session state, websocket transport, validation.   |
| LangGraph Orchestrator | Incident workflow state machine and routing across agent nodes.                        |
| Question Engine        | Generates/prioritizes diagnostic questions across technical/process/safety.            |
| Decision Engine        | Hypotheses, confidence, risk, constraints, Decision Brief, escalation decision inputs. |
| Escalation Engine      | Trigger evaluation, routing, expert handoff package, SLA tracking.                     |
| Safety/Governance      | Policy blocks, prerequisites, risk tightening, audit and review controls.              |
| Decision Memory        | Postgres + Qdrant patterns and prior incident retrieval; tenant isolated.              |
| Observability          | Metrics, logs, traces, alerts.                                                         |

## 4.2 Data Stores {#data-stores}

|                  |                |                                                                        |                                  |
|------------------|----------------|------------------------------------------------------------------------|----------------------------------|
| **Store**        | **Technology** | **What it contains**                                                   | **Notes**                        |
| Relational Store | PostgreSQL     | Tenants, users, incidents, Q&A, briefs, escalations, audit events      | Consistency + reporting          |
| Vector Store     | Qdrant         | Embeddings for patterns, incident summaries, expert reasoning snippets | Tenant namespaces, hybrid search |
| Cache/Queue      | Redis          | Session cache, rate limits, workflow state, background jobs            | Recommended                      |
| Object Store     | S3-compatible  | Attachments referenced by incidents                                    | Encrypted at rest                |

# 5. LangGraph Workflow and Nodes {#langgraph-workflow-and-nodes}

LangGraph represents the incident lifecycle as a state machine. Each node is an agent (or deterministic service) that consumes the incident state and emits state updates. The router decides which node runs next.

Hard boundary: the graph and agents produce decisions and constraints, but never operational execution steps.

## 5.1 Core Graph States {#core-graph-states}

- NEW_INCIDENT: initial report collected.

- SCREENING: severity/safety gating.

- DIAGNOSIS_LOOP: iterative questioning + hypothesis updates + retrieval.

- DECISION_BRIEF_READY: options ready for presentation.

- AWAITING_OUTCOME: user executes outside system and reports outcome.

- ESCALATED: expert handoff created and routed.

- RESOLVED: verification complete, memory updated.

## 5.2 Graph Node List (Agents) {#graph-node-list-agents}

|                           |                                              |                                                 |                                                    |
|---------------------------|----------------------------------------------|-------------------------------------------------|----------------------------------------------------|
| **Node / Agent**          | **Inputs**                                   | **Outputs**                                     | **Primary responsibility**                         |
| Incident Intake Agent     | free text report, asset context, attachments | incident record, initial summary                | Create incident card and normalize report          |
| Screening Agent           | incident card                                | impact, scope, safety level, initial risk score | Pre-classification and safety gating               |
| Question Generation Agent | state + retrieved evidence                   | ranked questions list                           | Generate/select technical/process/safety questions |
| Answer Interpreter Agent  | user answer + context                        | facts, contradictions, signal flags             | Convert answers into structured fields             |
| Retrieval Agent           | state + summary                              | top-k similar patterns and incidents            | Query Decision Memory (Postgres + Qdrant)          |
| Hypothesis Update Agent   | facts + hypotheses                           | updated hypotheses, confidence, risk delta      | Maintain hypotheses and compute confidence/risk    |
| Safety Constraint Agent   | state + risk                                 | constraints, blocks, prerequisites              | Enforce safety constraints; tighten on failures    |
| Decision Brief Agent      | state + constraints + evidence               | decision options, risks, escalation guidance    | Generate Decision Brief (no repair steps)          |
| Escalation Agent          | state + reason                               | handoff package, routing decision               | Build package, route, open escalation case         |
| Memory Write Agent        | final decision + outcome                     | pattern updates + embeddings                    | Store verified patterns in Qdrant                  |
| Audit Agent               | all events                                   | immutable logs                                  | Audit trails for compliance and review             |

# 6. Agent Responsibilities (Detailed) {#agent-responsibilities-detailed}

## 6.1 Incident Intake Agent {#incident-intake-agent}

Purpose: Convert raw user input into a structured incident card while preserving the original text.

Key steps: normalize report; extract asset/time/symptoms; create tenant-isolated incident record; store attachments as object references.

Outputs: Incident Card v0 and initial retrieval summary.

## 6.2 Screening Agent {#screening-agent}

Purpose: Determine safety posture and severity quickly.

Outputs: safety_level, impact, scope, initial risk score, and gating flags that can force escalation.

## 6.3 Retrieval Agent (Decision Memory) {#retrieval-agent-decision-memory}

Purpose: Retrieve similar incidents and verified decision patterns.

Flow: build query; hybrid search (keyword + vector) within tenant namespace; return top-k evidence and any mandatory escalation rules.

Rule: no cross-tenant retrieval by default.

## 6.4 Question Generation Agent {#question-generation-agent}

Purpose: Ask the next best question to reduce uncertainty.

Strategy: safety questions first when safety unknown; prefer hypothesis-separating questions; stop when confidence is sufficient.

## 6.5 Answer Interpreter Agent {#answer-interpreter-agent}

Purpose: convert answers into structured facts and flags.

Responsibilities: parse values; detect contradictions; produce signal flags for router and safety layer.

## 6.6 Hypothesis Update Agent {#hypothesis-update-agent}

Purpose: Maintain ranked hypotheses across technical/process causes.

Outputs: hypothesis set, confidence, and risk delta; handles process failures as first-class hypotheses.

## 6.7 Safety Constraint Agent {#safety-constraint-agent}

Purpose: Convert safety into constraints and blocks.

Tightening: each failed attempt increases caution and can force escalation.

## 6.8 Decision Brief Agent {#decision-brief-agent}

Purpose: Produce Decision Brief with options, risks, constraints, and escalation guidance.

Boundary: no repair steps, disassembly instructions, or command sequences.

## 6.9 Escalation Agent {#escalation-agent}

Purpose: Create escalation case and expert package.

Package includes: summary, classification, Q&A timeline, attempts, hypotheses, constraints, attachments, optional read-only snapshots; routes to correct level with SLA tracking.

## 6.10 Memory Write Agent {#memory-write-agent}

Purpose: Store reusable decision logic after closure.

Capture: turning-point signals, why attempts failed, when escalation should trigger next time; excludes repair instructions and proprietary tuning details.

# 7. Data Model (High-Level) {#data-model-high-level}

|                   |                                         |                                                                               |
|-------------------|-----------------------------------------|-------------------------------------------------------------------------------|
| **Table**         | **Purpose**                             | **Key columns**                                                               |
| tenants           | Customer isolation boundary             | id, name, deployment_mode, created_at                                         |
| users             | Auth identities and roles               | id, tenant_id, email, role, status                                            |
| assets            | Registered systems/equipment            | id, tenant_id, site_id, asset_type, tags                                      |
| incidents         | Incident master record                  | id, tenant_id, asset_id, status, severity, safety_level, opened_at, closed_at |
| incident_messages | Webchat transcript                      | id, incident_id, sender_type, content, created_at                             |
| incident_facts    | Structured facts extracted from answers | id, incident_id, key, value, confidence                                       |
| decision_briefs   | Generated Decision Brief versions       | id, incident_id, version, brief_json, created_at                              |
| escalations       | Escalation case tracking                | id, incident_id, level, routed_to, status, opened_at, closed_at               |
| expert_notes      | Expert reasoning capture                | id, escalation_id, note, turning_point, created_at                            |
| decision_patterns | Verified patterns for reuse             | id, tenant_id, title, pattern_json, embedding_id                              |
| audit_events      | Immutable audit trail                   | id, tenant_id, incident_id, actor, event_type, payload, created_at            |

# 8. API Surface (Backend) {#api-surface-backend}

|                                 |            |                                          |
|---------------------------------|------------|------------------------------------------|
| **Endpoint**                    | **Method** | **Purpose**                              |
| /api/v1/incidents               | POST       | Create incident (initial report)         |
| /api/v1/incidents/{id}          | GET        | Fetch incident card and current state    |
| /api/v1/incidents/{id}/messages | POST       | Send message/answer into chat thread     |
| /ws/incidents/{id}              | WS         | Real-time chat and state updates         |
| /api/v1/incidents/{id}/briefs   | GET        | List Decision Brief versions             |
| /api/v1/incidents/{id}/outcome  | POST       | Report outcome (success/failure/partial) |
| /api/v1/incidents/{id}/escalate | POST       | Manual escalation trigger                |
| /api/v1/escalations/{id}        | GET        | Get escalation case and status           |
| /api/v1/admin/policies          | GET/PUT    | Manage safety rules, thresholds, routing |
| /api/v1/admin/patterns          | GET        | Browse Decision Memory patterns          |

# 9. Security, Privacy, and Compliance {#security-privacy-and-compliance}

- Tenant isolation at auth, storage, and vector namespaces.

- TLS in transit; encryption at rest for Postgres, Qdrant, and object storage.

- RBAC roles: technician, supervisor, expert, admin; escalation level controls.

- Immutable audit events for decisions, escalations, and policy changes.

- Data minimization: store only what is required for decision logic and auditability.

- No execution APIs: the platform must not trigger machine actions or control changes.

# 10. Deployment and Operations {#deployment-and-operations}

- Frontend: React via CDN.

- Backend: API + Orchestrator services (containers).

- Workers: embeddings, indexing, summarization jobs.

- Data: Postgres, Qdrant, Redis, Object storage, Observability stack.

# 11. Acceptance Criteria and Deliverables {#acceptance-criteria-and-deliverables}

- Escalation triggers are configurable per incident class and tenant.

- Escalation activation logs include: trigger_reason(s), evidence, risk score, confidence, question/attempt counts.

- Expert handoff package includes full context (summary + timeline + constraints + attachments).

- Decision Brief never includes repair steps or command sequences.

- Decision Memory retrieval improves over time and remains tenant-isolated.

# 12. Questions:  {#questions}

- Are there specific safety red-line keywords or patterns (e.g., \"fire\", \"leak\", \"high voltage\") that should force immediate escalation regardless of other scores?

- Should the question loop allow the user to manually skip a question or say \"I don\'t know\" and how should that affect risk/confidence scoring?

- Which type of questions do we want to ask from the user? Can you share examples?

- Can you also share an examples of a recommendation?
