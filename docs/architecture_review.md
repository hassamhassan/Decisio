# Decisio — Architecture Review Report

**Current architecture vs [Draft English Translation](file:///home/code/Decisio/_MConverter.eu_Decisio_Draft_English_Translation.md)**

---

## Current Architecture

```
START → Incident Intake → Screening → Retrieval (Qdrant)
                                         ↓
                              Question Agent (10-step)
                                         ↓
                               ┌── User Answer ──┐
                               ↓                  ↓
                         Answer Interpreter   (skip/quit)
                               ↓
                         Hypothesis Update
                               ↓
                         Safety Constraint
                               ↓
                    ┌──── diagnosis_router ────┐
                    ↓          ↓               ↓
              [continue]  [confident]    [escalation]
              Question    Decision       Escalation Agent
              Agent       Brief          → Decision Brief
                               ↓
                              END
                               
Post-Decision:
    Outcome Capture → [success] → Memory Write → END
                    → [failure] → re-diagnose or escalate
                    
    Expert Capture → Qdrant store → END
```

---

## ✅ Architecture Matches (No Changes Needed)

| Draft Section | Requirement | Our Architecture |
|--------------|-------------|------------------|
| §1 | Independent decision layer, not execution | ✅ All agents enforce no-repair boundary |
| §2.1 | Webchat → diagnostic questions → brief | ✅ Full pipeline: intake → questions → brief |
| §2.2 | No commands, no control, no repair steps | ✅ Decision Brief Agent prompt blocks these |
| §2.3 | Sits between reporting and execution | ✅ Report → Decision Layer → END (no execution) |
| §4.1 | Decision before action | ✅ Brief generates options, not fixes |
| §4.2 | Questions > answers | ✅ 10-step framework drives diagnosis |
| §4.3 | Process failures as first-class | ✅ Screening detects early, Question Agent injects |
| §4.4 | Safety as constraints, not instructions | ✅ Safety Agent = blocks + constraints + escalation |
| §4.5 | Human-in-the-loop | ✅ Operator answers questions, approves decisions |
| §4.6 | Failure is information | ✅ Outcome Capture tightens safety on failure |
| §4.7 | Expertise becomes institutional | ✅ Expert Capture → Qdrant memory |
| §5 Steps 1-5 | Report → Classify → Question → Analyze → Brief | ✅ Full pipeline matches |
| §5 Steps 6-8 | Execute → Outcome → Memory | ✅ Outcome Capture + Memory Write agents |
| §7 | Technical + Process + Safety questions | ✅ 10-step categories cover all three |
| §8 | Process failures detected early | ✅ Screening + early injection in steps 1-3 |
| §9 | Safety tightens on failure, blocks unsafe | ✅ Safety Agent + Outcome Capture |
| §10 | 5 escalation levels with full context | ✅ Escalation Agent with handoff package |
| §11 | Capture WHY, not HOW | ✅ Expert Capture stores signals, not repair steps |
| §13 | 10-step root cause framework | ✅ DIAGNOSTIC_CATEGORIES in state |
| §13 | Decision Memory store | ✅ Qdrant with verified patterns |
| §13 | Safety & Governance layer | ✅ Safety Agent + escalation routing |

---

## ⚠️ Architecture Gaps — Changes Recommended

### GAP 1: Missing Decision Loop (§5 — Critical)
**Draft says:** "Decisio is not a straight line (report→fix). It is a decision loop: Report → Questions → Decision → Execution → Outcome → Update."

**Current:** Our graph goes `Decision Brief → END`. After the brief, there's no graph-level loop back if the user tries the decision and it fails.

**Fix needed:** Wire the outcome sub-graph into `main.py` so the full loop works:
```
Decision Brief → User Executes → Outcome Capture 
    → [success] → Memory Write → Close
    → [failure] → Tighten Safety → Re-enter Diagnosis Loop
    → [escalation] → Escalation Agent → Expert Capture
```

> [!IMPORTANT]
> This is the #1 architectural gap. The draft explicitly says this is a **loop**, not a line.

---

### GAP 2: No "Decision Authority" Field (§19.3)
**Draft template shows:** `Decision Authority: Technician level` and `Escalation Path: Line Supervisor (if needed)`

**Current:** `DecisionBrief` model has `escalation_guidance` but no explicit `decision_authority` field.

**Fix:** Add `decision_authority: str` to `DecisionBrief` model and update the brief agent prompt.

---

### GAP 3: Incident Status Lifecycle (§5, §19.2)
**Draft says:** Incidents move through states: Open → In Diagnosis → Brief Generated → Executing → Resolved / Escalated.

**Current:** We have a `status` field but no formal lifecycle enforcement. The status values are inconsistent across agents.

**Fix:** Define an enum of valid statuses and enforce transitions:
```python
INCIDENT_STATUSES = [
    "OPEN",               # Just reported
    "SCREENING",          # Being classified
    "DIAGNOSING",         # In the Q&A loop
    "BRIEF_GENERATED",    # Decision Brief ready
    "EXECUTING",          # User is attempting resolution
    "RESOLVED",           # Outcome = success, memory written
    "ESCALATED",          # Escalation triggered
    "CLOSED",             # Fully closed with memory
]
```

---

### GAP 4: No Recurrence Detection (§9, §10)
**Draft says:** "Same failure repeats in a short window" is an escalation trigger.

**Current:** No mechanism to detect if the same asset/symptoms appeared recently.

**Fix:** Before screening, query Qdrant for recent incidents with same asset. If found within a time window, auto-increase risk score and flag recurrence.

---

### GAP 5: Information Source Priority Not Enforced (§6)
**Draft defines 7-level priority:**
1. Safety constraints (absolute)
2. Human input (field truth)
3. Expert knowledge (past interventions)
4. Decision Memory (patterns)
5. Technical manuals
6. System integrations
7. Cross-facility patterns

**Current:** All sources feed into agents equally. Safety constraint priority is enforced by the Safety Agent, but there's no explicit source weighting in hypothesis or question logic.

**Fix (P3):** Add source-priority weighting to the Hypothesis Agent prompt so it ranks facts from safety/human input higher than memory patterns.

---

## ✅ Architecture Verdict

| Aspect | Verdict |
|--------|---------|
| Core pipeline (intake → brief) | ✅ **Perfect** |
| 10-step diagnostic framework | ✅ **Perfect** |
| Agent separation of concerns | ✅ **Perfect** |
| Safety constraints & escalation | ✅ **Perfect** |
| Decision Memory (Qdrant RAG) | ✅ **Perfect** |
| Expert knowledge capture | ✅ **Perfect** |
| No-execution boundary | ✅ **Perfect** |
| Outcome loop (not line) | ⚠️ **Needs wiring in main.py** |
| Decision authority field | ⚠️ **Minor model addition** |
| Status lifecycle | ⚠️ **Needs enum + enforcement** |
| Recurrence detection | ⚠️ **Missing feature** |
| Source priority ranking | ⚠️ **Low priority, prompt-level fix** |

### Bottom Line

> **The architecture is fundamentally correct.** No structural redesign is needed. The agent graph, state model, diagnostic framework, safety logic, and memory system all align with the draft.
>
> **5 gaps found** — all fixable without changing the architecture:
> - 1 wiring fix in `main.py` (outcome loop)
> - 1 model field addition (decision authority)
> - 1 enum definition (status lifecycle)
> - 1 new feature (recurrence detection)
> - 1 prompt enhancement (source priority)
