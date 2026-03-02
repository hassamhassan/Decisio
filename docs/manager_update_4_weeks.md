# Decisio — 4-Week Development Update
**Date:** February 18, 2026
**Project:** Decisio — Operational Decision Support System
**Prepared by:** Development Team

---

## Executive Summary

Decisio is an AI-powered operational decision-support system that guides operators through structured incident diagnosis using a 10-step diagnostic framework. Over the past 4 weeks, we have built out the core agent architecture, LLM integration, and initial diagnostic workflow.

---

## Week 1 — Architecture & Foundation

- Finalized the system architecture based on the Decisio Development Guide v1.3
- Selected technology stack: **LangGraph** (orchestration), **Groq API** (LLM inference), **Pydantic** (data validation)
- Defined core entities: Incident, Incident Card, Diagnostic Question, Decision Brief, Escalation Case
- Designed the end-to-end workflow: Report → Screening → Diagnosis Loop → Decision Brief → Outcome
- Set up the project repository, virtual environment, and dependency management

## Week 2 — State Model & Data Architecture

- Implemented the **LangGraph State Model** (`DecisioState`) as the shared data contract across all agents
- Created Pydantic sub-models for structured data:
  - `IncidentCard` — incident metadata, severity, safety level, symptoms
  - `Question` — diagnostic questions with category, rationale, and safety flags
  - `QAPair` — question-answer history tracking
  - `Hypothesis` — ranked root-cause hypotheses with probability scores
- Integrated the **10-Step Diagnostic Framework** into the state model:
  1. Trigger Condition → 2. Internal Equipment → 3. Upstream Equipment → 4. Downstream Equipment → 5. Control System → 6. Instrumentation → 7. Utilities → 8. Process Conditions → 9. Procedure/Human → 10. Verification & Closure
- Built the **Groq LLM utility** (`get_llm()`) for reusable, configurable LLM access

## Week 3 — Agent Development

- **Incident Intake Agent** — Converts free-text incident reports into structured Incident Cards via LLM extraction. Captures asset ID, symptoms, severity, safety level, and a normalized summary. Includes robust JSON parsing with fallback handling.
- **Question Generation Agent** — Generates 3 ranked diagnostic questions per the 10-step framework. Implements safety-first strategy (safety questions prioritized when safety is unknown/danger). Tracks diagnostic step progression (1–10) in state. Includes comprehensive fallback questions for all 10 framework steps.
- Both agents validated with Pydantic models for output consistency

## Week 4 — Graph Wiring, CLI & Testing

- Wired both agents into a **LangGraph StateGraph**: `Incident Intake → Question Generation → END`
- Built an interactive **CLI entry point** (`main.py`) for live testing:
  - Accepts free-text incident reports
  - Displays structured Incident Card with all extracted fields
  - Shows diagnostic questions with category labels, rationale, and expected answer types
- Completed integration verification — all imports, graph compilation, and model validation passing
- Created project documentation and environment configuration

---

## Current System Capabilities

| Capability | Status |
|------------|--------|
| Accept free-text incident repor
ts | ✅ Complete |
| Extract structured Incident Cards (asset, symptoms, severity, safety) | ✅ Complete |
| Generate diagnostic questions (10-step framework) | ✅ Complete |
| Safety-first question prioritization | ✅ Complete |
| Diagnostic step tracking (1–10) | ✅ Complete |
| Interactive CLI for testing | ✅ Complete |
| Groq LLM integration | ✅ Complete |

---

## 10-Week Roadmap

### Week 5 — Screening Agent & Answer Interpreter

| Task | Description |
|------|-------------|
| Screening Agent | Auto-classify severity, safety level, impact, scope; compute initial risk score |
| Answer Interpreter Agent | Parse user answers into structured facts, detect contradictions, produce signal flags |
| State model updates | Add screening fields and fact-extraction schema |

### Week 6 — Full Diagnosis Loop

| Task | Description |
|------|-------------|
| Iterative Q&A loop | Wire the graph into a loop: Question → User Answer → Interpret → Next Step |
| Step progression | Auto-advance through all 10 diagnostic steps based on answers |
| Confidence gating | Stop the loop early when confidence exceeds threshold |
| Question budget | Enforce max question count per step and overall |

### Week 7 — Hypothesis & Safety Agents

| Task | Description |
|------|-------------|
| Hypothesis Update Agent | Maintain ranked hypotheses across technical/process causes; update confidence & risk delta |
| Safety Constraint Agent | Enforce safety blocks, prerequisite checks, risk tightening on failed attempts |
| Escalation trigger evaluation | Check safety red-lines, risk thresholds, attempt limits per framework §3.1 |

### Week 8 — Decision Brief & Escalation Agents

| Task | Description |
|------|-------------|
| Decision Brief Agent | Generate decision options with risks, constraints, and escalation guidance (no repair steps) |
| Escalation Agent | Build expert handoff package, routing logic, SLA tracking |
| Memory Write Agent | Store verified decision patterns and turning-point signals after closure |

### Week 9 — Decision Memory & API Layer

| Task | Description |
|------|-------------|
| Qdrant vector store | Set up tenant-isolated vector storage for decision patterns |
| Retrieval Agent | Hybrid search (keyword + vector) for similar past incidents |
| FastAPI backend | REST endpoints: create incident, send messages, get briefs, manual escalation |
| WebSocket support | Real-time chat and state update streaming |
| PostgreSQL schema | Incidents, Q&A, briefs, escalations, audit events |

### Week 10 — Testing, Polish & Deployment

| Task | Description |
|------|-------------|
| Integration tests | End-to-end tests across the full 10-step diagnostic flow |
| Load & error testing | API rate limiting, LLM failure handling, retry logic |
| Webchat UI (React) | Basic incident reporting UI with guided Q&A and Decision Brief viewer |
| Deployment config | Docker containers, environment configs, observability setup |
| Documentation | API docs, operator guide, deployment runbook |

### Milestone Summary

```
Week 1–4  ██████████████████████████░░░░░░░░░░░░░░░░░░░░░░░░░░  40%  ✅ Done
Week 5    ████████                                                           Screening + Interpreter
Week 6    ████████                                                           Diagnosis Loop
Week 7    ████████                                                           Hypothesis + Safety
Week 8    ████████                                                           Decision Brief + Escalation
Week 9    ████████                                                           Memory + API
Week 10   ████████                                                           Testing + Deployment
```

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Groq API rate limits during high-volume usage | Implement retry logic and request queuing |
| LLM output quality varies per incident type | Comprehensive fallback questions + Pydantic validation |
| 10-step framework may need tuning per industry | Make framework steps configurable per tenant |

---

## Key Files

| File | Purpose |
|------|---------|
| `src/state/state.py` | State model + 10-step diagnostic framework |
| `src/llm.py` | Groq LLM integration |
| `src/agents/incident_intake_agent.py` | Incident Card extraction agent |
| `src/agents/question_agent.py` | Diagnostic question generation agent |
| `src/graph.py` | LangGraph workflow orchestration |
| `main.py` | Interactive CLI entry point |

---

*For questions or a live demo, please reach out to the development team.*
