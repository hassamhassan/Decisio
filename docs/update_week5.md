# Decisio — Development Update (Week 5)
**Date:** February 19, 2026  
**Project:** Decisio — Operational Decision Support System  
**Prepared by:** Development Team

---

## Summary

In a single session we completed all work originally planned for Weeks 5–8, delivering 6 new agents, a full iterative diagnosis loop, Qdrant-based retrieval, and the complete LangGraph workflow with escalation routing.

---

## Work Completed Today

### 1. State Model Expansion
- Added 4 new Pydantic models: `Fact`, `DecisionOption`, `DecisionBrief`, `RetrievedPattern`
- Added system-wide thresholds: confidence (80%), risk escalation (8.0), max questions (20)
- Added new state fields: `user_answer`, `current_question`, `contradictions`, `escalation_triggered`, `escalation_reasons`, `screening_complete`, `retrieved_patterns`, `questions_asked_count`

### 2. Screening Agent (`screening_agent.py`)
- Auto-classifies severity, safety level, impact, and scope
- Computes initial risk score (0–10) using severity × safety × uncertainty formula
- Checks for immediate escalation triggers (danger level, risk ≥ 8.0, gating flags)

### 3. Answer Interpreter Agent (`answer_interpreter_agent.py`)
- Parses operator answers into structured `Fact` objects with confidence scores
- Detects contradictions against previously known facts
- Produces signal flags: `safety_concern`, `needs_escalation`, `contradiction`, `uncertainty`
- Records Q&A history with diagnostic step tracking

### 4. Retrieval Agent (`retrieval_agent.py`) — RAG
- Qdrant vector search for similar past incidents using `all-MiniLM-L6-v2` embeddings
- In-memory Qdrant for development, production-ready for persistent server
- Seeded with 5 sample decision patterns (compressor failure, pump leak, control valve, power outage, instrument drift)
- LLM-based fallback when Qdrant is unavailable
- Checks for mandatory escalation patterns from memory

### 5. Hypothesis Update Agent (`hypothesis_agent.py`)
- Maintains 2–5 ranked root-cause hypotheses with probabilities
- Integrates facts, Q&A history, retrieved patterns, and contradictions
- Computes overall confidence score and risk delta
- Supports technical, process, and external hypothesis categories

### 6. Safety Constraint Agent (`safety_agent.py`)
- Enforces safety constraints, blocks (hard stops), and escalation triggers
- Programmatic escalation checks per §3.1 of the architecture guide:
  - Risk score ≥ 8.0
  - Low confidence after question budget exhausted
  - 3+ contradictions preventing stable hypotheses
  - Safety blocks present
  - Mandatory escalation patterns
- Applies risk adjustments and tightens constraints after failed attempts

### 7. Decision Brief Agent (`decision_brief_agent.py`)
- Generates 2–4 decision options with risks, constraints, and confidence scores
- Marks one option as recommended
- Includes risk summary and escalation guidance
- **Strictly enforces the "no repair steps" boundary** — decisions only, no execution

### 8. Full LangGraph Workflow (`graph.py`)
- Complete pipeline: Intake → Screening → Retrieval → Question Loop → Decision Brief
- Iterative diagnosis loop auto-advances through all 10 diagnostic steps
- Conditional routing with 3 exit conditions:
  - Confidence ≥ 80% → generate brief
  - Risk ≥ 8.0 or safety blocks → escalate
  - Questions ≥ 20 or all 10 steps done → generate brief
- Separate answer-processing sub-graph for the Q&A loop

### 9. Interactive CLI (`main.py`)
- 3-phase flow: Initial Processing → Diagnosis Loop → Decision Brief
- Real-time status display: risk, confidence, step, hypotheses, escalation
- Supports skip, quit, and "I don't know" answers
- Displays retrieved similar incidents, diagnostic questions, and full Decision Brief

---

## Current System Capabilities

| Capability | Status |
|------------|--------|
| Incident intake (free-text → structured card) | ✅ Complete |
| Auto-screening (severity, safety, impact, risk) | ✅ Complete |
| Qdrant RAG retrieval (similar past incidents) | ✅ Complete |
| 10-step diagnostic question framework | ✅ Complete |
| Answer interpretation (facts, contradictions, signals) | ✅ Complete |
| Hypothesis tracking (ranked root causes) | ✅ Complete |
| Safety constraints & escalation triggers | ✅ Complete |
| Decision Brief generation (no repair steps) | ✅ Complete |
| Iterative diagnosis loop with auto-advance | ✅ Complete |
| Confidence gating (80% threshold) | ✅ Complete |
| Escalation routing (risk, safety, contradictions) | ✅ Complete |
| Interactive CLI with full workflow | ✅ Complete |

---

## Architecture

```
START → Incident Intake → Screening ─┬─→ [danger/high risk] → Decision Brief → END
                                      └─→ Retrieval (Qdrant) → Question Agent
                                                                     ↓
                                            ┌────────────────── User Answer
                                            ↓
                                      Answer Interpreter → Hypothesis Update
                                            → Safety Constraint ─┬─→ [escalate] → Decision Brief → END
                                                                  └─→ [continue] → Question Agent
                                                                  └─→ [confident] → Decision Brief → END
```

---

## Key Files (12 Total)

| File | Purpose |
|------|---------|
| `src/state/state.py` | State model, 6 Pydantic models, thresholds |
| `src/llm.py` | Groq LLM factory |
| `src/agents/incident_intake_agent.py` | Free-text → Incident Card |
| `src/agents/screening_agent.py` | Severity/safety/risk classification |
| `src/agents/retrieval_agent.py` | Qdrant vector search + fallback |
| `src/agents/question_agent.py` | 10-step diagnostic questions |
| `src/agents/answer_interpreter_agent.py` | Fact extraction & contradiction detection |
| `src/agents/hypothesis_agent.py` | Ranked hypotheses & confidence |
| `src/agents/safety_agent.py` | Constraints, blocks, escalation |
| `src/agents/decision_brief_agent.py` | Decision options (no repair steps) |
| `src/graph.py` | Full LangGraph workflow + sub-graph |
| `main.py` | Interactive CLI |

---

## Remaining Work

| Item | Description |
|------|-------------|
| Escalation Agent | Expert handoff package, routing, SLA tracking |
| Memory Write Agent | Store verified patterns after closure |
| FastAPI + WebSocket API | REST endpoints for frontend integration |
| PostgreSQL schema | Persistent data storage |
| React Webchat UI | Operator-facing interface |
| Integration tests | End-to-end testing across all 10 steps |
| Deployment | Docker, observability, documentation |

---

*For a live demo, run: `source venv/bin/activate && python main.py`*
