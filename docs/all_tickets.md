# Decisio — All Tickets (Completed + Remaining)

**Project:** Decisio — Operational Decision Support System  
**Date:** February 19, 2026  
**Total Tickets:** 35 | **Completed:** 17 | **Remaining:** 18

---

# ✅ COMPLETED TICKETS

---

### T-01: Project Setup & Environment
**Status:** ✅ Done  
**Description:** Initialize project repo, virtual environment, dependencies, and environment configuration.  
**Tasks:**
- [x] Create project structure with `src/`, `src/agents/`, `src/state/` packages
- [x] Set up `requirements.txt` (langchain-groq, langgraph, pydantic, qdrant-client, sentence-transformers, fastapi, uvicorn, python-dotenv)
- [x] Create `.env` with GROQ_API_KEY and GROQ_MODEL placeholders
- [x] Create `__init__.py` files for all packages

**Files:** `requirements.txt`, `.env`, `src/__init__.py`, `src/agents/__init__.py`, `src/state/__init__.py`

---

### T-02: State Model & Data Architecture
**Status:** ✅ Done  
**Description:** Design and implement the shared LangGraph state schema with all Pydantic sub-models and the 10-step diagnostic framework.  
**Tasks:**
- [x] Create `DecisioState` TypedDict with all fields
- [x] Create `IncidentCard` model (ID, report, summary, asset, symptoms, severity, safety, status, impact, scope, risk score)
- [x] Create `Question` model (question, category, diagnostic_step, rationale, expected_answer_type, blocking_safety_flag)
- [x] Create `QAPair` model (question, answer, category, diagnostic_step, signals)
- [x] Create `Fact` model (key, value, confidence, source_step, contradiction)
- [x] Create `Hypothesis` model (description, probability, category, supporting_facts, contradicting_facts)
- [x] Create `DecisionOption` model (option_id, title, description, risks, constraints, confidence, recommended)
- [x] Create `DecisionBrief` model (incident_id, options, overall_confidence, risk_summary, safety_constraints, escalation_guidance)
- [x] Create `RetrievedPattern` model (pattern_id, title, similarity_score, signals, decision_taken, must_escalate)
- [x] Define `DIAGNOSTIC_CATEGORIES` list (10 categories)
- [x] Define thresholds: CONFIDENCE_THRESHOLD=0.80, RISK_ESCALATION_THRESHOLD=8.0, MAX_TOTAL_QUESTIONS=20

**File:** `src/state/state.py`

---

### T-03: Groq LLM Utility
**Status:** ✅ Done  
**Description:** Build a reusable factory function for ChatGroq instances with configurable model and temperature.  
**Tasks:**
- [x] Create `get_llm()` factory function
- [x] Load API key from `.env`
- [x] Default model: `llama-3.3-70b-versatile`, temperature: 0.2
- [x] Support model and temperature overrides per agent

**File:** `src/llm.py`

---

### T-04: Incident Intake Agent
**Status:** ✅ Done  
**Description:** Convert free-text incident reports into structured Incident Cards via LLM extraction.  
**Tasks:**
 Build system prompt for structured extraction
 Extract: normalized summary, asset ID, symptoms, severity, safety level
 Robust JSON parsing with markdown stripping
 Fallback mechanism when LLM output is unparseable
 Validate output through `IncidentCard` model

**File:** `src/agents/incident_intake_agent.py`

---

### T-05: Question Generation Agent (10-Step Framework)
**Status:** ✅ Done  
**Description:** Generate ranked diagnostic questions following the 10-step framework with safety-first prioritization and process failure early detection.  
**Tasks:**
- [x] Generate 3 questions per diagnostic step
- [x] Safety-first: include safety question when safety_level is unknown/danger
- [x] 10-step coverage: trigger, internal, upstream, downstream, control, instrumentation, utilities, process, procedure/human, verification
- [x] No-repeat check against Q&A history
- [x] Process failure early injection: include process question in steps 1-3 when suspected
- [x] Comprehensive fallback questions for all 10 steps
- [x] Validate through `Question` model

**File:** `src/agents/question_agent.py`

---

### T-06: Screening Agent
**Status:** ✅ Done  
**Description:** Auto-classify incidents by severity, safety, impact, scope, and compute initial risk score with process failure detection.  
**Tasks:**
- [x] Classify severity (low/medium/high/critical)
- [x] Classify safety level (safe/caution/danger/unknown)
- [x] Assess impact and scope (localized/unit-wide/plant-wide/multi-site)
- [x] Compute initial risk score (0-10)
- [x] Detect process failure indicators from initial report (§8)
- [x] Check for immediate escalation triggers (danger, risk ≥ 8.0, gating flags)
- [x] Set `process_failure_suspected` flag in state

**File:** `src/agents/screening_agent.py`

---

### T-07: Answer Interpreter Agent
**Status:** ✅ Done  
**Description:** Parse operator answers into structured facts, detect contradictions, and produce signal flags.  
**Tasks:**
- [x] Extract `Fact` objects from answers with confidence scores
- [x] Detect contradictions against existing facts
- [x] Produce signal flags: safety_concern, needs_escalation, contradiction, uncertainty
- [x] Record Q&A history with diagnostic step
- [x] Check for escalation signals in answers
- [x] Track questions_asked_count

**File:** `src/agents/answer_interpreter_agent.py`

---

### T-08: Retrieval Agent (Decision Memory / RAG)
**Status:** ✅ Done  
**Description:** Vector search for similar past incidents using Qdrant. Returns only real matches above similarity threshold — no fabricated patterns.  
**Tasks:**
- [x] Qdrant setup with in-memory client (dev) / persistent server (prod)
- [x] Sentence-transformer embeddings (all-MiniLM-L12-v2)
- [x] Seed 5 sample decision patterns
- [x] Search with similarity threshold (0.6) — skip low matches
- [x] Check if collection is empty — skip search entirely
- [x] No LLM fallback — real patterns only or empty list
- [x] Check for mandatory escalation patterns from memory

**File:** `src/agents/retrieval_agent.py`

---

### T-09: Hypothesis Update Agent
**Status:** ✅ Done  
**Description:** Maintain ranked root-cause hypotheses with probabilities across technical, process, and external categories.  
**Tasks:**
- [x] Generate 2-5 ranked hypotheses (probabilities sum to ~1.0)
- [x] Support categories: technical, process, external
- [x] Integrate facts, Q&A history, retrieved patterns, contradictions
- [x] Track supporting and contradicting facts per hypothesis
- [x] Compute overall confidence score and risk delta

**File:** `src/agents/hypothesis_agent.py`

---

### T-10: Safety Constraint Agent
**Status:** ✅ Done  
**Description:** Enforce safety constraints, blocks, and escalation triggers per the draft §9.  
**Tasks:**
- Generate safety constraints and blocks (hard stops)
- Programmatic escalation checks: risk ≥ 8.0, low confidence + budget exhausted, 3+ contradictions, safety blocks
- Apply risk adjustments after failures
- Handle mandatory escalation patterns
- Update incident card safety level
- Merge with existing constraints (no duplicates)

**File:** `src/agents/safety_agent.py`

---

### T-11: Decision Brief Agent
**Status:** ✅ Done  
**Description:** Generate decision options with risks, constraints, and escalation guidance. Never includes repair steps.  
**Tasks:**

**File:** `src/agents/decision_brief_agent.py`

---

### T-12: Outcome Capture Agent
**Status:** ✅ Done  
**Description:** Process operator's outcome report (success/failure) after execution attempt. Close the decision loop per §5 steps 6-7.  
**Tasks:**
- Accept operator outcome report (success/failure/partial)
- On failure: increment attempts, tighten safety, trigger escalation after 2+ fails
- On success: capture root cause and turning-point signal (§11)
- Apply risk adjustments based on outcome
- Set status: RESOLVED_PENDING_MEMORY / ESCALATION_REQUIRED / RETRY_DIAGNOSIS

**File:** `src/agents/outcome_capture_agent.py`

---

### T-13: Memory Write Agent
**Status:** ✅ Done  
**Description:** Store verified decision patterns into Qdrant after successful resolution per §5 step 8 and §11.  
**Tasks:**

**File:** `src/agents/memory_write_agent.py`

---

### T-14: Full LangGraph Workflow
**Status:** ✅ Done  
**Description:** Wire all agents into a complete LangGraph pipeline with iterative diagnosis loop and conditional routing.  
**Tasks:**
- [x] Pipeline: Intake → Screening → Retrieval → Question Loop → Decision Brief
- [x] Answer sub-graph: Answer Interpreter → Hypothesis → Safety → Advance Step
- [x] Conditional routing: confidence ≥ 80%, risk ≥ 8.0, questions ≥ 20, step > 10
- [x] Post-screening escalation check
- [x] Post-safety escalation check

**File:** `src/graph.py`

---

### T-15: Interactive CLI
**Status:** ✅ Done  
**Description:** Build full interactive CLI for testing the entire Decisio workflow.  
**Tasks:**
- [x] 3-phase flow: Initial Processing → Diagnosis Loop → Decision Brief
- [x] Real-time status display (risk, confidence, step, hypotheses)
- [x] Support skip, quit, "I don't know" answers
- [x] Display retrieved patterns, questions, and full Decision Brief
- [x] Error handling for missing API key

**File:** `main.py`

---

### T-16: Process Failure Early Detection
**Status:** ✅ Done  
**Description:** Detect process failures early in the diagnosis flow, not just at step 9 (§8).  
**Tasks:**
- [x] Screening Agent detects process failure indicators from initial report
- [x] Question Agent injects process/human questions in steps 1-3 when suspected
- [x] Process failure indicators tracked in state

**Files:** `src/agents/screening_agent.py`, `src/agents/question_agent.py`

---

### T-17: Project Documentation
**Status:** ✅ Done  
**Description:** Create project documentation, roadmaps, and alignment reports.  
**Tasks:**
- [x] Manager update with 10-week roadmap
- [x] Alignment report vs draft document
- [x] Weekly development update
- [x] 20 remaining task tickets
- [x] Completed task tickets

**Files:** `docs/manager_update_4_weeks.md`, `docs/alignment_report.md`, `docs/update_week5.md`, `docs/tickets.md`

---

---

# 📋 REMAINING TICKETS

---

### T-18: Escalation Agent — Expert Handoff Package
**Status:** 🔲 Not Started | **Priority:** P1 | **Section:** §10  
**Description:** Build agent that creates a full-context handoff package when escalation is triggered.  
**Tasks:**
Generate escalation document with: incident report, Q&A timeline, failed attempts, decision options, safety constraints, hypotheses
Route to correct level: supervisor → specialist → expert → OEM → admin
Include SLA tracking fields
Wire into LangGraph after safety agent

---

### T-19: Escalation Level Routing
**Status:** 🔲 Not Started | **Priority:** P1 | **Section:** §10  
**Description:** Classify escalation level based on severity, failed attempts, risk score, and pattern match.  
**Tasks:**
- [ ] Define 5 escalation levels with routing rules
- [ ] Auto-select level based on state inputs
- [ ] Allow manual override escalation

---

### T-20: Expert Knowledge Capture Flow
**Status:** 🔲 Not Started | **Priority:** P1 | **Section:** §11  
**Description:** Interactive flow to capture expert decision logic after resolution.  
**Tasks:**
- [ ] Ask expert: what signal confirmed the cause
- [ ] Ask expert: why symptoms were misleading
- [ ] Ask expert: when to escalate in the future
- [ ] Store as decision pattern in Qdrant (no repair steps)

---

### T-21: Outcome Retry Loop in Graph
**Status:** 🔲 Not Started | **Priority:** P1 | **Section:** §5, §9  
**Description:** Wire outcome capture back into the graph so failure loops back to diagnosis.  
**Tasks:**

---

### T-22: Verification & Closure Gate
**Status:** 🔲 Not Started | **Priority:** P1 | **Section:** §13  
**Description:** Prevent closure until trigger conditions normalize and verification is recorded.  
**Tasks:**
- [ ] Add verification gate node after outcome success
- [ ] Require trigger normalization confirmation
- [ ] Record verification steps before allowing CLOSED status

---

### T-23: Fast Pre-Classification Path
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §14  
**Description:** 2-3 quick screening questions before the full LLM screening for fast routing.  
**Tasks:**
Define 3 quick classification questions (impact, scope, safety)
Simple rule-based routing (no LLM needed)
Skip full screening if clear classification

---

### T-24: Category-Driven Question Bundling
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §14  
**Description:** Group questions by category so the operator answers related questions together.  
**Tasks:**
- [ ] Bundle 3 questions per diagnostic step
- [ ] Allow operator to answer all at once
- [ ] Parse multi-answer responses

---

### T-25: FastAPI REST Endpoints
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §24  
**Description:** Build the backend API for web and mobile clients.  
**Tasks:**
POST /incidents — create incident
POST /incidents/{id}/messages — send answer
GET /incidents/{id}/brief — get decision brief
POST /incidents/{id}/escalate — manual escalation
GET /incidents/{id}/status — get current state

---

### T-26: WebSocket Real-Time Chat
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §24  
**Description:** Real-time chat for the Webchat interface.  
**Tasks:**
WebSocket endpoint for session-based chat
Stream agent responses to client
Handle reconnection and session recovery

---

### T-27: PostgreSQL Persistent Storage
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §24  
**Description:** Replace in-memory state with database persistence.  
**Tasks:**
- [ ] Design schema: incidents, qa_history, decision_briefs, escalations, audit_events
- [ ] Create SQLAlchemy models
- [ ] Implement CRUD operations
- [ ] Migration scripts

---

### T-28: React Webchat UI
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §13, §14  
**Description:** Build the operator-facing web interface.  
**Tasks:**
Incident report input form
Guided Q&A chat interface
Decision Brief display (one-screen)
Safety constraint warnings
Escalation status display
Incident history list

---

### T-29: Decision Brief One-Screen Format
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §14, §19.3  
**Description:** Format the brief into a single-screen summary per the template.  
**Tasks:**
- [ ] Analysis summary section
- [ ] Options with RECOMMENDED / NOT RECOMMENDED tags
- [ ] Safety constraints block
- [ ] Decision authority level
- [ ] Escalation path

---

### T-30: Tenant Isolation
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §13  
**Description:** Multi-customer data separation.  
**Tasks:**

---

### T-31: Audit Trail
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §13  
**Description:** Immutable log of every decision step for compliance.  
**Tasks:**
- [ ] Log: report, questions, answers, options, selection, outcome
- [ ] Immutable storage (append-only)
- [ ] Audit report generation

---

### T-32: Safety Tightening on Recurrence
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §9  
**Description:** Auto-tighten constraints when same failure recurs in short window.  
**Tasks:**
- [ ] Detect recurrence (same asset, similar symptoms, short window)
- [ ] Auto-increase starting risk score
- [ ] Add tighter safety constraints from previous incident

---

### T-33: Read-Only System Integrations
**Status:** 🔲 Not Started | **Priority:** P3 | **Section:** §6  
**Description:** Optional connectors to SCADA/CMMS for verification only.  
**Tasks:**
- [ ] Define read-only connector interface
- [ ] Build SCADA/monitoring adapter
- [ ] Verification-only — no write, no control

---

### T-34: Authentication & RBAC
**Status:** 🔲 Not Started | **Priority:** P3 | **Section:** §24  
**Description:** SSO and role-based access control.  
**Tasks:**
- [ ] Integrate Auth0 or Keycloak
- [ ] Roles: Operator, Supervisor, Expert, Admin
- [ ] Role-based feature visibility

---

### T-35: Integration & Load Testing + Deployment
**Status:** 🔲 Not Started | **Priority:** P2 | **Section:** §27  
**Description:** End-to-end testing and production deployment setup.  
**Tasks:**
- [ ] Full 10-step diagnostic flow tests
- [ ] Escalation flow tests
- [ ] Outcome + memory write tests
- [ ] Load testing: API rate limits, LLM retries, <2s response
- [ ] Docker containers for all services
- [ ] Monitoring and alerting setup
- [ ] Deployment runbook and API docs

---

---

# Dashboard

| Status | Count | Tickets |
|--------|-------|---------|
| ✅ Completed | 17 | T-01 to T-17 |
| 🔲 Remaining P1 | 5 | T-18 to T-22 |
| 🔲 Remaining P2 | 11 | T-23 to T-32, T-35 |
| 🔲 Remaining P3 | 2 | T-33, T-34 |
| **Total** | **35** | |
