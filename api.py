"""
Decisio — FastAPI Backend

REST API for the Decisio decision-support system.
Manages incident sessions and routes to the LangGraph pipeline.
Persists all data to PostgreSQL.
"""

from __future__ import annotations

import asyncio
import os
import uuid
import logging
import traceback
import re
from datetime import datetime,timezone
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI,HTTPException,Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field

from dotenv import load_dotenv

load_dotenv()

from src.graph import build_graph,build_answer_graph,build_outcome_graph
from src.agents.decision_brief_agent import decision_brief_agent
from src.agents.retrieval_agent import retrieval_agent
from src.agents.outcome_capture_agent import outcome_capture_agent
from src.agents.memory_write_agent import memory_write_agent
from src.agents.escalation_agent import escalation_agent
from src.agents.expert_capture_agent import expert_capture_agent

from src.db.session import init_db,close_db,get_session
from src.db import crud
from src.auth import require_auth,require_admin,require_company_admin,require_super_admin,TokenData,is_escalation_type,_LEGACY_ESCALATION_TYPES
from src.sanitize import sanitize_user_input
from src.services.escalation_service import EscalationService
from src.websocket.manager import ws_manager
from src.websocket.router import router as ws_router

logger = logging.getLogger(__name__)

# ── Graphs ──────────────────────────────────────────────────────────

intake_graph = build_graph()
answer_graph = build_answer_graph()
outcome_graph = build_outcome_graph()

# ── In-memory fallback (kept for backward compatibility) ────────────

sessions: dict[str,dict] = {}
_db_available = True  # Mutable container to avoid `global` in async


def use_db() -> bool:
    return _db_available


# ── App lifecycle ───────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB. Shutdown: close DB."""
    global _db_available
    try:
        await init_db()
        logger.info("✅ PostgreSQL connected and tables ready")
        _db_available = True
    except Exception as e:
        logger.warning(f"⚠️  PostgreSQL not available ({e}),falling back to in-memory")
        _db_available = False
    yield
    if _db_available:
        await close_db()


# ── App setup ───────────────────────────────────────────────────────

app = FastAPI(
    title="Decisio API",
    description="Operational Decision Support System",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket escalation chat (ensure ws:// or wss:// for client connections)
_ws_base = (os.getenv("WS_BASE_URL") or "http://localhost:8020").rstrip("/")
if _ws_base.startswith("https://"):
    WS_BASE_URL = "wss://" + _ws_base[8:]
elif _ws_base.startswith("http://"):
    WS_BASE_URL = "ws://" + _ws_base[7:]
else:
    WS_BASE_URL = _ws_base
app.include_router(ws_router,tags=["websocket"])

# ── Request/Response models ─────────────────────────────────────────


class CreateIncidentRequest(BaseModel):
    report: str = Field(...,min_length=1,max_length=10_000)
    reported_by: str = Field(default="",max_length=200)
    language: str = Field(default="en",max_length=5,description="UI language code (en or ar)")


class AnswerRequest(BaseModel):
    answer: str = Field(...,min_length=1,max_length=5_000)
    language: str = Field(default="en",max_length=5,description="UI language code (en or ar)")


class OutcomeRequest(BaseModel):
    outcome: str = Field(...,min_length=1,max_length=5_000)
    selected_option_id: Optional[int] = Field(
        default=None,
        description="decision_brief.options[].option_id the operator ran before Success.",
    )
    language: str = Field(default="en",max_length=5,description="UI language code (en or ar)")


class BriefRequest(BaseModel):
    language: str = Field(default="en",max_length=5,description="UI language code (en or ar)")


class VerificationRequest(BaseModel):
    trigger_normalized: bool
    verification_notes: str = Field(default="",max_length=5_000)


class IncidentResponse(BaseModel):
    incident_id: str
    status: str
    report: str = ""
    qa_history: Optional[list] = None
    incident_card: Optional[dict] = None
    questions: Optional[list] = None
    current_diagnostic_step: Optional[int] = None
    hypotheses: Optional[list] = None
    confidence: Optional[float] = None
    risk_score: Optional[float] = None
    decision_brief: Optional[dict] = None
    escalation: Optional[dict] = None
    escalation_triggered: Optional[bool] = False
    escalation_reasons: Optional[list] = None
    retrieved_patterns: Optional[list] = None
    memory_guidance: Optional[str] = None
    retrieval_confidence: Optional[float] = None
    safety_constraints: Optional[list] = None
    outcome: Optional[str] = None
    failed_attempts: Optional[int] = 0
    memory_written: Optional[bool] = False
    mttd_seconds: Optional[float] = None
    verification_confirmed: Optional[bool] = False
    clarification_question: Optional[str] = None


async def _safe_background(coro) -> None:
    """Wrapper for asyncio.create_task — logs unhandled exceptions instead of swallowing them."""
    try:
        await coro
    except Exception:
        logger.exception("Background task failed")


# Retries for PENDING_ESCALATION_CONFIG reprocessing (transient DB / LLM flakes)
_REPROCESS_ESCALATION_MAX_ATTEMPTS = 5
_REPROCESS_ESCALATION_BASE_DELAY_SEC = 1.5


async def _reprocess_pending_escalations(company_id: int) -> None:
    """Re-run escalation_agent on every incident that was parked as
    PENDING_ESCALATION_CONFIG for this company.  Called in the background
    after an admin saves the first escalation level so parked incidents are
    immediately re-routed to the correct escalation level.

    Per-incident retries with exponential backoff reduce limbo when updates
    fail transiently. After all attempts fail,the incident stays pending
    until the next admin save triggers another run or an operator reloads
    config (same function).
    """
    try:
        from sqlalchemy import select as sa_select
        from src.db.models import Incident

        async with get_session() as session:
            result = await session.execute(
                sa_select(Incident).where(
                    Incident.company_id == company_id,
                    Incident.status == "PENDING_ESCALATION_CONFIG",
                )
            )
            pending = result.scalars().all()

        for inc in pending:
            last_err: Exception | None = None
            for attempt in range(_REPROCESS_ESCALATION_MAX_ATTEMPTS):
                try:
                    state = crud.incident_to_state(inc)
                    updated = escalation_agent(state)
                    if updated:
                        state.update(updated)
                    async with get_session() as session:
                        await crud.update_incident(session,str(inc.id),state)
                    async with get_session() as session:
                        await crud.mark_all_notifications_read_for_incident(
                            session,company_id,str(inc.id)
                        )
                    last_err = None
                    break
                except Exception as inner_err:
                    last_err = inner_err
                    logger.warning(
                        "Reprocess pending escalation attempt %s/%s failed for incident %s: %s",
                        attempt + 1,
                        _REPROCESS_ESCALATION_MAX_ATTEMPTS,
                        inc.id,
                        inner_err,
                    )
                    if attempt + 1 < _REPROCESS_ESCALATION_MAX_ATTEMPTS:
                        delay = _REPROCESS_ESCALATION_BASE_DELAY_SEC * (2**attempt)
                        await asyncio.sleep(delay)

            if last_err is not None:
                logger.error(
                    "Giving up reprocessing PENDING_ESCALATION_CONFIG for incident %s after %s attempts; "
                    "incident remains pending until the next escalation config save",
                    inc.id,
                    _REPROCESS_ESCALATION_MAX_ATTEMPTS,
                    exc_info=(type(last_err),last_err,last_err.__traceback__),
                )
    except Exception as e:
        logger.warning("_reprocess_pending_escalations failed: %s",e)


async def _ensure_escalation_session(state: dict,user: TokenData) -> None:
    """
    When escalation is triggered,create an escalation session (unassigned by default),
    and add session_id + ws_url to state["escalation"]. Idempotent if already set.

    If the escalation matrix is not yet configured (pending_config),skip the
    session creation and instead create an admin notification so the admin
    sees a bell-icon alert and can configure the matrix.
    """
    if not state.get("escalation_triggered") or user.company_id is None:
        return

    # ── No matrix configured: notify admin and return ──────────────
    escalation_info = state.get("escalation") or {}
    if escalation_info.get("pending_config"):
        try:
            async with get_session() as session:
                incident_card = state.get("incident_card") or {}
                incident_id = (
                    state.get("_session_id")
                    or incident_card.get("incident_id")
                    or "unknown"
                )
                summary = incident_card.get("normalized_summary") or incident_card.get("symptoms","")
                reasons = escalation_info.get("escalation_reasons") or []
                notif = await crud.create_admin_notification(
                    session,
                    company_id=user.company_id,
                    notification_type="PENDING_ESCALATION_CONFIG",
                    title="⚠️ Escalation Matrix Not Configured",
                    message=(
                        f"Incident '{summary or incident_id}' requires escalation but "
                        "no escalation matrix has been configured for your company. "
                        "Please set up escalation levels and rules in "
                        "Admin Portal → Escalation."
                    ),
                    incident_id=incident_id,
                    payload={
                        "incident_id": incident_id,
                        "summary": summary,
                        "escalation_reasons": reasons,
                        "reported_by": user.username,
                    },
                )
                try:
                    await ws_manager.notify_company(
                        user.company_id,
                        {
                            "type": "admin_notification",
                            "notification": crud._notification_to_dict(notif),
                        },
                    )
                except Exception as ws_err:
                    logger.warning("Failed to push pending-config notification via WS: %s",ws_err)
        except Exception as notif_err:
            logger.warning("Failed to create pending-escalation notification: %s",notif_err)
        return

    if state.get("escalation_session_id"):
        # This incident already has an escalation session bound to it.
        # Do not create another one.
        return
    try:
        async with get_session() as session:
            svc = EscalationService(session)
            escalation_info = state.get("escalation") or {}
            # escalation_agent sets escalation_level as an integer.
            req_level_val = escalation_info.get("escalation_level")
            try:
                req_level = int(req_level_val) if req_level_val is not None else None
            except Exception:
                req_level = None
            esc = await svc.create_session(
                company_id=user.company_id,
                user_id=user.user_id,
                required_level=req_level,
            )
            session_id_val = str(esc.id)
            state["escalation_session_id"] = session_id_val
        state["escalation"] = state.get("escalation") or {}
        state["escalation"]["session_id"] = session_id_val
        state["escalation"]["ws_url"] = f"{WS_BASE_URL}/ws/chat/{user.company_id}/{session_id_val}"
        state["escalation"]["escalation"] = True
        # Notify all experts in-real time about the new escalation session
        try:
            await ws_manager.notify_company(user.company_id,{
                "type": "new_escalation",
                "session_id": session_id_val,
                "company_id": user.company_id,
                "required_level": req_level,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass  # Non-critical: experts still have polling fallback
    except Exception as e:
        logger.error("Escalation session creation failed: %s",e,exc_info=True)
        raise HTTPException(status_code=500,detail="Failed to create escalation session in database")


def _state_to_response(state: dict) -> IncidentResponse:
    """Convert internal state to API response. Guards against None values from graph."""
    if state is None:
        state = {}
        
    incident_card = state.get("incident_card")
    inc_id = incident_card.get("incident_id") if incident_card else None
    if not inc_id:
        inc_id = state.get("_session_id") or ""
        
    return IncidentResponse(
        incident_id=inc_id,
        status=state.get("status") or "UNKNOWN",
        report=state.get("report") or "",
        qa_history=state.get("qa_history") or [],
        incident_card=incident_card,
        questions=state.get("questions") or [],
        current_diagnostic_step=state.get("current_diagnostic_step") or 1,
        hypotheses=state.get("hypotheses") or [],
        confidence=state.get("confidence") if state.get("confidence") is not None else 0.0, # 0.0 is valid
        risk_score=state.get("risk_score") if state.get("risk_score") is not None else 0.0,
        decision_brief=state.get("decision_brief"),
        escalation=state.get("escalation"),
        escalation_triggered=state.get("escalation_triggered") or False,
        escalation_reasons=state.get("escalation_reasons") or [],
        retrieved_patterns=state.get("retrieved_patterns") or [],
        memory_guidance=state.get("memory_guidance"),
        retrieval_confidence=state.get("retrieval_confidence"),
        safety_constraints=state.get("safety_constraints") or [],
        outcome=state.get("outcome") or "pending",
        failed_attempts=state.get("failed_attempts") or 0,
        memory_written=state.get("memory_written") or False,
        mttd_seconds=state.get("mttd_seconds"),
        verification_confirmed=state.get("verification_confirmed") or False,
        clarification_question=state.get("clarification_question"),
    )


# ── State helpers ───────────────────────────────────────────────────


async def _save_state(incident_id: str,state: dict):
    """Save state to PostgreSQL or in-memory fallback.

    During the guided intake phase (no incident_card yet) the incident must not
    appear in the sidebar or the DB.  We stage it in the in-memory ``sessions``
    dict only.  Once a real incident_card has been built we persist to
    PostgreSQL and evict the staging entry so there are no duplicate reads.
    """
    has_card = state.get("incident_card") is not None

    if use_db() and has_card:
        async with get_session() as session:
            existing = await crud.get_incident(session,incident_id)
            if existing:
                await crud.update_incident(session,incident_id,state)
            else:
                await crud.create_incident(session,state,incident_id)

            # If the incident references a machine that is not in the
            # equipment registry,raise an admin notification so the
            # admin can add it. Deduplicated per-incident by CRUD.
            if state.get("asset_not_registered") and state.get("company_id") is not None:
                ic = state.get("incident_card") or {}
                missing_id = state.get("asset_not_registered_id") or ic.get("asset_id") or ""
                summary = ic.get("normalized_summary") or ic.get("report","")
                notif = await crud.create_admin_notification(
                    session,
                    company_id=state["company_id"],
                    notification_type="MACHINE_NOT_REGISTERED",
                    title="⚠️ Machine not in equipment registry",
                    message=(
                        f"Incident '{summary or incident_id}' references machine '{missing_id}',"
                        "which is not in the equipment registry. Please add this equipment "
                        "in the Admin Portal → Equipment."
                    ),
                    incident_id=incident_id,
                    payload={
                        "incident_id": incident_id,
                        "missing_machine_id": missing_id,
                        "summary": summary,
                    },
                )
                try:
                    await ws_manager.notify_company(
                        state["company_id"],
                        {
                            "type": "admin_notification",
                            "notification": crud._notification_to_dict(notif),
                        },
                    )
                except Exception as ws_err:
                    logger.warning("Failed to push admin notification via WS: %s",ws_err)

        # Remove from in-memory staging now that it is committed to DB
        sessions.pop(incident_id,None)
    else:
        # Either DB is not configured,or the incident_card is not yet set
        # (clarification phase).  Keep in the in-memory staging store only.
        sessions[incident_id] = state


async def _load_state(incident_id: str,company_id: int | None = None) -> dict | None:
    """Load state from PostgreSQL or in-memory fallback.
    Tenant isolation: when company_id is provided,only returns state if incident belongs
    to that tenant (returns None otherwise → 404). All incident routes pass user.company_id.

    When using PostgreSQL,incidents that are still in the guided intake phase
    (not yet committed to DB) are held in the in-memory ``sessions`` staging
    dict.  We check there as a second step if the DB lookup returns nothing.
    """
    if use_db():
        async with get_session() as session:
            inc = await crud.get_incident(session,incident_id,company_id=company_id)
            if inc:
                return crud.incident_to_state(inc)
        # Not in DB yet — check in-memory staging (clarification / intake phase)
        state = sessions.get(incident_id)
        if state and company_id is not None and state.get("company_id") != company_id:
            return None  # Wrong tenant — treat as not found (404)
        return state
    else:
        state = sessions.get(incident_id)
        if state and company_id is not None and state.get("company_id") != company_id:
            return None  # Wrong tenant — treat as not found (404)
        return state


# ── Routes ──────────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"status": "ok","service": "decisio","storage": "postgresql" if use_db() else "in-memory"}


def _ensure_chat_access(user: TokenData) -> None:
    """Only viewer role can use the chat console."""
    if user.user_type != "viewer":
        raise HTTPException(
            status_code=403,
            detail="Chat console is only available for viewer accounts.",
        )


@app.post("/api/incidents",response_model=IncidentResponse)
async def create_incident(req: CreateIncidentRequest,user: TokenData = Depends(require_auth)):
    """Create a new incident and run intake → screening → retrieval → questions."""
    _ensure_chat_access(user)
    if not req.report.strip():
        raise HTTPException(400,"Report cannot be empty")
    if user.company_id is None:
        raise HTTPException(400,"Super admin has no company; use a company admin or operator account to create incidents.")

    session_id = str(uuid.uuid4())

    try:
        sanitized_report = sanitize_user_input(req.report,max_length=10_000)
        ui_lang = req.language if req.language in ("en","ar") else "en"
        state = intake_graph.invoke({
            "report": sanitized_report,
            "company_id": user.company_id,
            "language": ui_lang,
            "current_diagnostic_step": 1,
            "questions_asked_count": 0,
            "qa_history": [],
            "facts": [],
            "hypotheses": [],
            "contradictions": [],
            "safety_constraints": [],
            "safety_blocks": [],
            "escalation_triggered": False,
            "escalation_reasons": [],
            "confidence": 0.0,
            "failed_attempts": 0,
            "outcome": "pending",
            "status": "OPEN",
            "diagnosis_start_time": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Intake error: {e}")
        raise HTTPException(500,detail=f"Processing error: {str(e)}")

    if state is None:
        state = {}

    # Ensure company_id is propagated
    state["company_id"] = user.company_id
    state["language"] = ui_lang

    state["_session_id"] = session_id
    incident_id = session_id

    # Set reported_by and incident_id from user's auth token and session_id
    ic = state.get("incident_card")
    if ic is not None:
        ic["incident_id"] = incident_id
        ic["reported_by"] = req.reported_by or user.username
        state["incident_card"] = ic

    await _ensure_escalation_session(state,user)
    await _save_state(incident_id,state)
    return _state_to_response(state)


@app.get("/api/incidents/{incident_id}",response_model=IncidentResponse)
async def get_incident(incident_id: str,user: TokenData = Depends(require_auth)):
    """Get the current state of an incident (tenant-scoped). Returns 404 if wrong tenant."""
    # super_admin has no company_id; can load any incident by ID
    state = await _load_state(incident_id,company_id=user.company_id if user.company_id is not None else None)
    if not state:
        raise HTTPException(404,"Incident not found")
    return _state_to_response(state)


@app.post("/api/incidents/{incident_id}/answer",response_model=IncidentResponse)
async def submit_answer(incident_id: str,req: AnswerRequest,user: TokenData = Depends(require_auth)):
    """Submit an answer to the current diagnostic question."""
    _ensure_chat_access(user)
    state = await _load_state(incident_id,company_id=user.company_id if user.company_id is not None else None)
    if not state:
        raise HTTPException(404,"Incident not found")

    questions = state.get("questions") or []
    current_q = (questions[0] if questions else None) or {}

    answer = sanitize_user_input(req.answer.strip(),max_length=5000)
    if not answer:
        answer = "I don't know / skipped"
    ui_lang = req.language if req.language in ("en","ar") else "en"
    state["language"] = ui_lang

    try:
        if not state.get("screening_complete") or not state.get("incident_card"):
            # Still in the guided intake phase (symptoms → machine → complete).
            # Append the user's reply so problem_intake_agent can read it,then
            # clear the clarification flag and re-run the intake graph.
            # intake_phase is preserved in state so the agent advances correctly.
            state["report"] = state.get("report","") + f"\n\n[User Clarification]: {answer}"
            qa_hist = state.get("qa_history") or []
            qa_hist.append({
                "question": state.get("clarification_question",""),
                "answer": answer,
                "category": "clarification",
                "diagnostic_step": 1,
                "signals": [],
            })
            state["qa_history"] = qa_hist
            state.pop("clarification_question",None)
            # Merge graph output into pre-invoke state so API-only keys
            # (company_id,_session_id,etc.) are never dropped when the
            # compiled graph returns a partial channel update.
            _pre_intake = dict(state)
            _out = intake_graph.invoke(_pre_intake) or {}
            state = {**_pre_intake,**_out}
        else:
            _pre_answer = dict(state)
            _out = answer_graph.invoke({
                **_pre_answer,
                "user_answer": answer,
                "current_question": current_q,
            }) or {}
            state = {**_pre_answer,**_out}
    except Exception as e:
        logger.error(f"Answer processing error: {e}")
        raise HTTPException(500,f"Processing error: {str(e)}")

    if state is None:
        state = {}

    # Ensure reported_by and incident_id are set if incident card was just created
    ic = state.get("incident_card")
    if ic is not None:
        ic["incident_id"] = incident_id
        if not ic.get("reported_by"):
            ic["reported_by"] = user.username
        state["incident_card"] = ic

    # If no brief yet and diagnosis ended,generate one.
    # We wait longer before generating the brief so the bot can ask
    # more targeted questions and build higher confidence.
    if not state.get("decision_brief") and (
        (state.get("confidence") or 0) >= 0.85
        or (state.get("current_diagnostic_step") or 1) > 8
        or (state.get("escalation_triggered") and (state.get("current_diagnostic_step") or 1) > 4)
    ):
        try:
            brief_update = decision_brief_agent(state)
            if brief_update:
                state.update(brief_update)
        except Exception as e:
            logger.error("Failed to generate decision brief in background: %s",e,exc_info=True)

    state["_session_id"] = incident_id

    await _ensure_escalation_session(state,user)

    # Persist state first so the incident row is guaranteed to exist in the DB
    # before we try to insert a child QA record.
    await _save_state(incident_id,state)

    # QA rows: crud.create_incident and crud.update_incident already sync
    # state["qa_history"] into QARecord (delta append). Do not call
    # add_qa_record here — it duplicated rows and risked deadlocks.

    return _state_to_response(state)


@app.post("/api/incidents/{incident_id}/brief",response_model=IncidentResponse)
async def generate_brief(incident_id: str,req: BriefRequest = None,user: TokenData = Depends(require_auth)):
    """Force generate a Decision Brief with current information."""
    _ensure_chat_access(user)
    state = await _load_state(incident_id,company_id=user.company_id if user.company_id is not None else None)
    if not state:
        raise HTTPException(404,"Incident not found")
    if req:
        ui_lang = req.language if req.language in ("en","ar") else "en"
        state["language"] = ui_lang

    try:
        mem_update = retrieval_agent(state)
        if mem_update:
            state.update(mem_update)
        brief_update = decision_brief_agent(state)
        if brief_update:
            state.update(brief_update)
    except Exception as e:
        raise HTTPException(500,f"Brief generation error: {str(e)}")

    await _ensure_escalation_session(state,user)
    await _save_state(incident_id,state)
    return _state_to_response(state)


@app.post("/api/incidents/{incident_id}/outcome",response_model=IncidentResponse)
async def submit_outcome(incident_id: str,req: OutcomeRequest,user: TokenData = Depends(require_auth)):
    """Submit the outcome after executing the decision."""
    _ensure_chat_access(user)
    state = await _load_state(incident_id,company_id=user.company_id)
    if not state:
        raise HTTPException(404,"Incident not found")

    outcome_text = sanitize_user_input(req.outcome.strip(),max_length=5_000)
    if outcome_text.lower() == "success":
        outcome_notes = "Resolution successful — trigger conditions normalized."
    elif outcome_text.lower() == "failure":
        outcome_notes = "Resolution failed — problem persists."
    else:
        outcome_notes = outcome_text

    state["outcome_notes"] = outcome_notes
    state["status"] = "EXECUTING"
    ui_lang = req.language if req.language in ("en","ar") else "en"
    state["language"] = ui_lang

    # Operator-selected brief option (stored to Decision Memory on success)
    brief = state.get("decision_brief") or {}
    opts = brief.get("options") or []
    sel_id = req.selected_option_id
    if sel_id is not None:
        try:
            sel_id_int = int(sel_id)
        except (TypeError,ValueError):
            sel_id_int = None
        chosen = None
        if sel_id_int is not None:
            for o in opts:
                oid = o.get("option_id")
                try:
                    if oid is not None and int(oid) == sel_id_int:
                        chosen = o
                        break
                except (TypeError,ValueError):
                    continue
        else:
            chosen = None
        if chosen:
            state["chosen_decision_option"] = chosen
        else:
            state.pop("chosen_decision_option",None)
    else:
        state.pop("chosen_decision_option",None)

    # Run outcome capture
    try:
        outcome_update = outcome_capture_agent(state)
        if outcome_update:
            state.update(outcome_update)
    except Exception as e:
        raise HTTPException(500,f"Outcome processing error: {str(e)}")

    outcome = state.get("outcome","failure")
    status = state.get("status","")

    # Save outcome record
    if use_db():
        async with get_session() as session:
            await crud.add_outcome_record(
                session,
                incident_id=incident_id,
                attempt_number=state.get("failed_attempts",0) + (1 if outcome == "success" else 0),
                outcome=outcome,
                notes=outcome_notes,
            )

    if outcome == "success":
        # If an escalation chat session exists for this incident, close it now.
        # Success resolution should automatically end escalation so experts stop seeing it.
        esc_sid = (
            state.get("escalation_session_id")
            or (state.get("escalation") or {}).get("session_id")
        )
        if esc_sid and user.company_id is not None:
            try:
                esc_uuid = uuid.UUID(str(esc_sid))
            except Exception:
                esc_uuid = None
            if esc_uuid is not None:
                try:
                    async with get_session() as session:
                        svc = EscalationService(session)
                        await svc.close_session(esc_uuid, user.company_id)
                    # Notify chat participants + expert consoles.
                    try:
                        await ws_manager.broadcast(user.company_id, str(esc_uuid), {
                            "type": "session_closed",
                            "closed_by": user.user_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    except Exception:
                        pass
                    try:
                        await ws_manager.notify_company(user.company_id, {
                            "type": "session_closed",
                            "session_id": str(esc_uuid),
                            "closed_by": user.user_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning("Failed to auto-close escalation session on success: %s", e, exc_info=True)

        # Write to memory
        try:
            mem_update = memory_write_agent(state)
            if mem_update:
                state.update(mem_update)
        except Exception as e:
            logger.error("Failed to run memory write agent: %s",e,exc_info=True)
        # Mark as DONE to distinguish successfully completed incidents
        # from escalated / still-open ones in the UI.
        state["status"] = "SUCCESS"
        # Important: success means escalation must NOT be created/opened.
        # Earlier steps may have set escalation_triggered=True; clear it and
        # remove any existing escalation session payload so the UI won't
        # show the escalation chat.
        state["escalation_triggered"] = False
        state["escalation"] = None
        state["escalation_session_id"] = None

    elif state.get("escalation_triggered"):
        # Escalate
        try:
            esc_update = escalation_agent(state)
            if esc_update:
                state.update(esc_update)
        except Exception as e:
            logger.error("Failed to update incident outcome in DB: %s",e,exc_info=True)
        state["status"] = "ESCALATED"

    # Only create escalation sessions when escalation is still required.
    if state.get("escalation_triggered"):
        await _ensure_escalation_session(state,user)

    await _save_state(incident_id,state)
    return _state_to_response(state)


@app.post("/api/incidents/{incident_id}/verify",response_model=IncidentResponse)
async def verify_resolution(incident_id: str,req: VerificationRequest,user: TokenData = Depends(require_auth)):
    """Verify trigger condition normalization before closing (§13)."""
    _ensure_chat_access(user)
    state = await _load_state(incident_id,company_id=user.company_id if user.company_id is not None else None)
    if not state:
        raise HTTPException(404,"Incident not found")

    from datetime import datetime,timezone
    verification_ts = datetime.now(timezone.utc).isoformat()

    if not req.trigger_normalized:
        # Verification failed — reopen for retry
        state["verification_confirmed"] = False
        state["verification_notes"] = req.verification_notes
        state["verification_timestamp"] = verification_ts
        state["status"] = "RETRY_DIAGNOSIS"
        state["escalation_triggered"] = True
        reasons = list(state.get("escalation_reasons") or [])
        reasons.append("Verification failed: trigger condition NOT normalized")
        state["escalation_reasons"] = reasons

        # Escalate
        try:
            esc_update = escalation_agent(state)
            if esc_update:
                state.update(esc_update)
        except Exception:
            pass
        state["status"] = "ESCALATED"
    else:
        # Verification passed — record notes and proceed to memory write
        state["verification_confirmed"] = True
        state["verification_notes"] = req.verification_notes
        state["verification_timestamp"] = verification_ts
        try:
            mem_update = memory_write_agent(state)
            if mem_update:
                state.update(mem_update)
        except Exception:
            pass
        # Verified successful resolution → mark as DONE
        state["status"] = "SUCCESS"
        # Success means escalation must NOT be created/opened.
        state["escalation_triggered"] = False
        state["escalation"] = None
        state["escalation_session_id"] = None

    if state.get("escalation_triggered"):
        await _ensure_escalation_session(state,user)
    await _save_state(incident_id,state)
    return _state_to_response(state)


@app.get("/api/incidents")
async def list_incidents_endpoint(user: TokenData = Depends(require_auth)):
    """List incidents scoped to the current user's company. Super admin (no company_id) sees all."""
    # regular viewer users can only see their own incidents
    reported_by_filter = user.username if user.user_type == "viewer" else None

    if use_db():
        async with get_session() as session:
            return {"incidents": await crud.list_incidents(session,company_id=user.company_id,reported_by=reported_by_filter)}
    else:
        incidents = []
        for iid,state in sessions.items():
            if user.company_id is not None and state.get("company_id") != user.company_id:
                continue
            card = state.get("incident_card")
            # Skip clarification-phase sessions that have no incident_card yet
            if not card:
                continue
            if reported_by_filter and card.get("reported_by") != reported_by_filter:
                continue

            incidents.append({
                "incident_id": iid,
                "summary": card.get("normalized_summary",""),
                "severity": card.get("severity",""),
                "status": state.get("status",""),
                "confidence": state.get("confidence",0),
                "risk_score": state.get("risk_score",0),
            })
        return {"incidents": incidents}


# ── Operational Data API endpoints ──────────────────────────────────

from sqlalchemy import select as sa_select,update as sa_update,or_ as sa_or
from sqlalchemy.exc import IntegrityError
from src.db.models import (
    AdminNotification,Incident,Equipment,SafetyRule,EscalationLevel,EscalationRule,
    IncidentReport,Company,EscalationSession,EscalationMessage,
)


@app.get("/api/equipment")
async def list_equipment(user: TokenData = Depends(require_auth)):
    """List equipment from the asset registry (tenant-scoped)."""
    if user.company_id is None:
        raise HTTPException(403,"Super admin has no company scope.")
    async with get_session() as session:
        result = await session.execute(
            sa_select(Equipment)
            .where(Equipment.company_id == user.company_id)
            .order_by(Equipment.process_line,Equipment.id)
        )
        rows = result.scalars().all()
        return {
            "equipment": [
                {
                    "id": eq.id,
                    "name": eq.name,
                    "type": eq.equipment_type,
                    "process_line": eq.process_line,
                    "criticality": eq.criticality,
                    "description": eq.description,
                    "upstream_id": eq.upstream_id,
                    "downstream_id": eq.downstream_id,
                }
                for eq in rows
            ]
        }


@app.get("/api/equipment/{equipment_id}")
async def get_equipment(equipment_id: str,user: TokenData = Depends(require_auth)):
    """Get single equipment with upstream/downstream details (tenant-scoped)."""
    if user.company_id is None:
        raise HTTPException(403,"Super admin has no company scope.")
    async with get_session() as session:
        result = await session.execute(
            sa_select(Equipment)
            .where(Equipment.id == equipment_id.upper())
            .where(Equipment.company_id == user.company_id)
        )
        eq = result.scalar_one_or_none()
        if not eq:
            raise HTTPException(404,"Equipment not found")

        # Load upstream/downstream
        up = await session.get(Equipment,eq.upstream_id) if eq.upstream_id else None
        down = await session.get(Equipment,eq.downstream_id) if eq.downstream_id else None

        return {
            "id": eq.id,
            "name": eq.name,
            "type": eq.equipment_type,
            "process_line": eq.process_line,
            "criticality": eq.criticality,
            "description": eq.description,
            "upstream": {"id": up.id,"name": up.name,"type": up.equipment_type} if up else None,
            "downstream": {"id": down.id,"name": down.name,"type": down.equipment_type} if down else None,
        }


@app.get("/api/safety-rules")
async def list_safety_rules(equipment_type: str | None = None,user: TokenData = Depends(require_auth)):
    """List safety rules scoped to user's company."""
    if user.company_id is None:
        raise HTTPException(403,"Super admin has no company scope.")
    async with get_session() as session:
        query = sa_select(SafetyRule).where(
            SafetyRule.company_id == user.company_id
        ).order_by(SafetyRule.equipment_type,SafetyRule.sort_order)
        if equipment_type:
            query = query.where(
                (SafetyRule.equipment_type == equipment_type.lower()) |
                (SafetyRule.is_general == True)
            )
        result = await session.execute(query)
        rows = result.scalars().all()
        return {
            "rules": [
                {
                    "id": r.id,
                    "equipment_type": r.equipment_type,
                    "rule_text": r.rule_text,
                    "severity_class": r.severity_class,
                    "is_general": r.is_general,
                }
                for r in rows
            ]
        }


@app.get("/api/escalation-matrix")
async def get_escalation_matrix(user: TokenData = Depends(require_auth)):
    """Get the escalation matrix scoped to user's company."""
    if user.company_id is None:
        raise HTTPException(403,"Super admin has no company scope.")
    async with get_session() as session:
        levels_result = await session.execute(
            sa_select(EscalationLevel)
            .where(EscalationLevel.company_id == user.company_id)
            .order_by(EscalationLevel.level)
        )
        rules_result = await session.execute(
            sa_select(EscalationRule)
            .where(EscalationRule.company_id == user.company_id)
            .order_by(EscalationRule.sort_order)
        )
        return {
            "levels": [
                {"level": l.level,"name": l.name,"description": l.description}
                for l in levels_result.scalars().all()
            ],
            "rules": [
                {
                    "id": r.id,
                    "condition": r.condition,
                    "confidence_min": r.confidence_min,
                    "confidence_max": r.confidence_max,
                    "safety_impact": r.safety_impact,
                    "escalation_level": r.escalation_level,
                    "description": r.description,
                }
                for r in rules_result.scalars().all()
            ],
        }


# ── Admin Notifications ────────────────────────────────────────────


@app.get("/api/admin/notifications")
async def list_notifications(
    unread_only: bool = False,
    admin: TokenData = Depends(require_company_admin),
):
    """List admin notifications for the current company (newest first)."""
    async with get_session() as session:
        return {
            "notifications": await crud.list_admin_notifications(
                session,
                company_id=admin.company_id,
                unread_only=unread_only,
            )
        }


@app.get("/api/admin/notifications/count")
async def get_notification_count(admin: TokenData = Depends(require_company_admin)):
    """Return the number of unread admin notifications."""
    async with get_session() as session:
        count = await crud.get_unread_notification_count(session,admin.company_id)
    return {"unread_count": count}


@app.post("/api/admin/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    admin: TokenData = Depends(require_company_admin),
):
    """Mark a single notification as read."""
    async with get_session() as session:
        ok = await crud.mark_notification_read(session,notification_id,admin.company_id)
    if not ok:
        raise HTTPException(404,"Notification not found")
    return {"message": "Notification marked as read"}


@app.post("/api/admin/notifications/read-all")
async def mark_all_notifications_read(admin: TokenData = Depends(require_company_admin)):
    """Mark all notifications as read for this company."""
    async with get_session() as session:
        count = await crud.mark_all_notifications_read(session,admin.company_id)
    return {"message": f"{count} notification(s) marked as read"}


# ── Escalation Chat (REST) ─────────────────────────────────────────

@app.post("/api/escalation/sessions/{session_id}/close")
async def close_escalation_session(session_id: uuid.UUID,user: TokenData = Depends(require_auth)):
    """Close an escalation session. Allowed for participant (user/expert) or company admin."""
    if user.company_id is None:
        raise HTTPException(403,"Super admin has no company scope.")
    async with get_session() as session:
        svc = EscalationService(session)
        esc = await svc.get_session(session_id,user.company_id)
        if not esc:
            raise HTTPException(404,"Session not found")
        if esc.user_id != user.user_id and esc.expert_id != user.user_id and user.user_type != "admin":
            raise HTTPException(403,"Not a participant")
        closed = await svc.close_session(session_id,user.company_id)
    if not closed:
        raise HTTPException(400,"Session already closed")
    # EC11: broadcast session_closed to notification channel
    try:
        await ws_manager.notify_company(user.company_id,{
            "type": "session_closed",
            "session_id": str(session_id),
            "closed_by": user.user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.warning("Failed to broadcast session_closed event: %s",e,exc_info=True)
    return {"message": "Session closed","session_id": str(session_id)}


@app.get("/api/escalation/experts/available")
async def check_experts_available(user: TokenData = Depends(require_auth)):
    """Return whether any active escalation-level accounts exist for this company."""
    if user.company_id is None:
        raise HTTPException(403,"Super admin has no company scope.")
    async with get_session() as session:
        from sqlalchemy import func as sa_func
        count = await session.scalar(
            sa_select(sa_func.count()).select_from(User).where(
                User.company_id == user.company_id,
                User.is_active.is_(True),
                sa_or(
                    User.user_type.like("L%"),
                    User.user_type.in_(list(_LEGACY_ESCALATION_TYPES)),
                ),
            )
        ) or 0
    return {"has_experts": count > 0,"expert_count": count}


@app.get("/api/escalation/sessions")
async def list_escalation_sessions(user: TokenData = Depends(require_auth)):
    """
    List escalation sessions for the user's company.
    - Escalation-level users (L1,L2,...) see only sessions matching their required_level.
    - Regular users see only their own sessions.
    - Admins see all sessions.
    """
    if user.company_id is None:
        raise HTTPException(403,"Super admin has no company scope.")

    is_expert = is_escalation_type(user.user_type) or user.user_type == "admin"

    # Tenant routing by escalation level:
    # L1 sees only required_level=1,L2 sees only required_level=2,etc.
    # If required_level is NULL (older sessions),include them for compatibility.
    user_level: int | None = None
    if user.user_type:
        m = re.match(r"^L(\d+)$",user.user_type.strip())
        if m:
            try:
                user_level = int(m.group(1))
            except Exception:
                user_level = None

    async with get_session() as session:
        # Load users for display names
        query = sa_select(EscalationSession).where(
            EscalationSession.company_id == user.company_id,
            EscalationSession.status != "closed",
        ).order_by(EscalationSession.created_at.desc())

        if not is_expert:
            query = query.where(EscalationSession.user_id == user.user_id)
        elif user.user_type != "admin":
            from sqlalchemy import or_ as sa_or
            if user_level is not None:
                # Expert handler L1-L4: filter to their required level.
                query = query.where(
                    sa_or(
                        EscalationSession.required_level == user_level,
                        EscalationSession.required_level.is_(None),
                    )
                )
            else:
                # Legacy expert without a level: only see sessions without a specific required level
                query = query.where(EscalationSession.required_level.is_(None))

        result = await session.execute(query)
        sessions_list = result.scalars().all()

        # Load user display names
        user_ids = set()
        for s in sessions_list:
            user_ids.add(s.user_id)
            if s.expert_id:
                user_ids.add(s.expert_id)

        users_map = {}
        if user_ids:
            ur = await session.execute(
                sa_select(User).where(User.id.in_(user_ids))
            )
            for u in ur.scalars().all():
                users_map[u.id] = u.full_name or u.username

        return {
            "sessions": [
                {
                    "session_id": str(s.id),
                    "status": s.status,
                    "user_id": s.user_id,
                    "user_name": users_map.get(s.user_id,f"User #{s.user_id}"),
                    "expert_id": s.expert_id,
                    "expert_name": users_map.get(s.expert_id,None) if s.expert_id else None,
                    "required_level": s.required_level,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "ws_url": f"{WS_BASE_URL}/ws/chat/{user.company_id}/{s.id}",
                }
                for s in sessions_list
            ]
        }


@app.get("/api/escalation/sessions/{session_id}/messages")
async def list_escalation_messages(
    session_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    user: TokenData = Depends(require_auth)
):
    """List messages for an escalation session. Participant or admin only."""
    if user.company_id is None:
        raise HTTPException(403,"Super admin has no company scope.")
    async with get_session() as session:
        svc = EscalationService(session)
        esc = await svc.get_session(session_id,user.company_id)
        if not esc:
            raise HTTPException(404,"Session not found")
        # EC10: allow L-type users (escalation handlers) to view messages too
        if esc.user_id != user.user_id and esc.expert_id != user.user_id and user.user_type != "admin" and not is_escalation_type(user.user_type):
            raise HTTPException(403,"Not a participant")
        result = await session.execute(
            sa_select(EscalationMessage)
            .where(EscalationMessage.session_id == session_id,EscalationMessage.company_id == user.company_id)
            .order_by(EscalationMessage.created_at)
            .limit(limit)
            .offset(offset)
        )
        rows = result.scalars().all()
        return {
            "messages": [
                {
                    "id": str(m.id),
                    "sender_id": m.sender_id,
                    "sender_role": m.sender_role,
                    "message": m.message,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in rows
            ],
        }


@app.get("/api/incident-reports")
async def list_incident_reports(user: TokenData = Depends(require_auth)):
    """List historical incident reports scoped to user's company."""
    if user.company_id is None:
        raise HTTPException(403,"Super admin has no company scope.")
    async with get_session() as session:
        result = await session.execute(
            sa_select(IncidentReport)
            .where(IncidentReport.company_id == user.company_id)
            .order_by(IncidentReport.id)
        )
        rows = result.scalars().all()
        return {
            "reports": [
                {
                    "id": r.id,
                    "title": r.title,
                    "asset_id": r.asset_id,
                    "process_line": r.process_line,
                    "symptoms": r.symptoms,
                    "trigger_condition": r.trigger_condition,
                    "initial_assumption": r.initial_assumption,
                    "root_cause": r.root_cause,
                    "root_cause_category": r.root_cause_category,
                    "resolution": r.resolution,
                    "turning_point_signal": r.turning_point_signal,
                    "decision_taken": r.decision_taken,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "signals": r.signals,
                    "lessons": r.lessons,
                    "escalation_required": r.escalation_required,
                    "escalation_level": r.escalation_level,
                    "severity": r.severity,
                    "safety_level": r.safety_level,
                    "diagnosis_time_traditional": r.diagnosis_time_traditional,
                    "diagnosis_time_structured": r.diagnosis_time_structured,
                }
                for r in rows
            ]
        }


# ── Admin CRUD — Equipment ──────────────────────────────────────────

from src.auth import (
    hash_password,verify_password,create_access_token,
    USER_TYPES,
)


class EquipmentRequest(BaseModel):
    id: str
    name: str
    equipment_type: str
    process_line: str = ""
    criticality: str = "medium"
    description: str = ""
    upstream_id: Optional[str] = None
    downstream_id: Optional[str] = None


@app.post("/api/admin/equipment")
async def create_equipment(req: EquipmentRequest,admin: TokenData = Depends(require_company_admin)):
    """Create new equipment (admin only,scoped to admin's company). Upstream/downstream IDs are stored as-is (no existence check)."""
    try:
        async with get_session() as session:
            result = await session.execute(
                sa_select(Equipment)
                .where(Equipment.id == req.id.upper())
                .where(Equipment.company_id == admin.company_id)
            )
            if result.scalar_one_or_none():
                raise HTTPException(409,f"Equipment '{req.id.upper()}' already exists")

            eq = Equipment(
                id=req.id.upper(),
                company_id=admin.company_id,
                name=req.name,
                equipment_type=req.equipment_type.lower(),
                process_line=req.process_line,
                criticality=req.criticality.lower(),
                description=req.description,
                upstream_id=req.upstream_id.upper() if req.upstream_id else None,
                downstream_id=req.downstream_id.upper() if req.downstream_id else None,
            )
            session.add(eq)
            await session.flush()

            return {"message": f"Equipment '{eq.id}' created","equipment": {
                "id": eq.id,"name": eq.name,"type": eq.equipment_type,
                "process_line": eq.process_line,"criticality": eq.criticality,
            }}
    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(409,f"Equipment ID '{req.id.upper()}' is already taken.")
    except Exception as e:
        logger.warning("Create equipment failed: %s",e,exc_info=True)
        raise HTTPException(500,f"Failed to create equipment: {str(e)}")


class EquipmentUpdateRequest(BaseModel):
    name: Optional[str] = None
    equipment_type: Optional[str] = None
    process_line: Optional[str] = None
    criticality: Optional[str] = None
    description: Optional[str] = None
    upstream_id: Optional[str] = None
    downstream_id: Optional[str] = None


@app.put("/api/admin/equipment/{equipment_id}")
async def update_equipment(equipment_id: str,req: EquipmentUpdateRequest,admin: TokenData = Depends(require_company_admin)):
    """Update equipment (admin only,scoped to admin's company)."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(Equipment)
            .where(Equipment.id == equipment_id.upper())
            .where(Equipment.company_id == admin.company_id)
        )
        eq = result.scalar_one_or_none()
        if not eq:
            raise HTTPException(404,"Equipment not found")

        if req.name is not None: eq.name = req.name
        if req.equipment_type is not None: eq.equipment_type = req.equipment_type.lower()
        if req.process_line is not None: eq.process_line = req.process_line
        if req.criticality is not None: eq.criticality = req.criticality.lower()
        if req.description is not None: eq.description = req.description
        if req.upstream_id is not None: eq.upstream_id = req.upstream_id.upper() if req.upstream_id else None
        if req.downstream_id is not None: eq.downstream_id = req.downstream_id.upper() if req.downstream_id else None

        await session.flush()
        return {"message": f"Equipment '{eq.id}' updated"}


@app.delete("/api/admin/equipment/{equipment_id}")
async def delete_equipment(equipment_id: str,admin: TokenData = Depends(require_company_admin)):
    """Delete equipment (admin only,scoped to admin's company)."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(Equipment)
            .where(Equipment.id == equipment_id.upper())
            .where(Equipment.company_id == admin.company_id)
        )
        eq = result.scalar_one_or_none()
        if not eq:
            raise HTTPException(404,"Equipment not found")
        await session.delete(eq)
        await session.flush()
        return {"message": f"Equipment '{equipment_id.upper()}' deleted"}


# ── Admin CRUD — Safety Rules ──────────────────────────────────────

class SafetyRuleRequest(BaseModel):
    equipment_type: str
    rule_text: str
    severity_class: str = "constraint"  # block | constraint
    is_general: bool = False
    sort_order: int = 100


@app.post("/api/admin/safety-rules")
async def create_safety_rule(req: SafetyRuleRequest,admin: TokenData = Depends(require_company_admin)):
    """Create a new safety rule (admin only,scoped)."""
    async with get_session() as session:
        rule = SafetyRule(
            company_id=admin.company_id,
            equipment_type=req.equipment_type.lower(),
            rule_text=req.rule_text,
            severity_class=req.severity_class.lower(),
            is_general=req.is_general,
            sort_order=req.sort_order,
        )
        session.add(rule)
        await session.flush()

        return {"message": "Safety rule created","rule": {
            "id": rule.id,"equipment_type": rule.equipment_type,
            "rule_text": rule.rule_text,"severity_class": rule.severity_class,
        }}


class SafetyRuleUpdateRequest(BaseModel):
    equipment_type: Optional[str] = None
    rule_text: Optional[str] = None
    severity_class: Optional[str] = None
    is_general: Optional[bool] = None
    sort_order: Optional[int] = None


@app.put("/api/admin/safety-rules/{rule_id}")
async def update_safety_rule(rule_id: int,req: SafetyRuleUpdateRequest,admin: TokenData = Depends(require_company_admin)):
    """Update a safety rule (admin only)."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(SafetyRule).where(
                SafetyRule.id == rule_id,
                SafetyRule.company_id == admin.company_id,
            )
        )
        rule = result.scalar_one_or_none()
        if not rule:
            raise HTTPException(404,"Safety rule not found")

        if req.equipment_type is not None: rule.equipment_type = req.equipment_type.lower()
        if req.rule_text is not None: rule.rule_text = req.rule_text
        if req.severity_class is not None: rule.severity_class = req.severity_class.lower()
        if req.is_general is not None: rule.is_general = req.is_general
        if req.sort_order is not None: rule.sort_order = req.sort_order

        await session.flush()
        return {"message": f"Safety rule #{rule_id} updated"}


@app.delete("/api/admin/safety-rules/{rule_id}")
async def delete_safety_rule(rule_id: int,admin: TokenData = Depends(require_company_admin)):
    """Delete a safety rule (admin only)."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(SafetyRule).where(
                SafetyRule.id == rule_id,
                SafetyRule.company_id == admin.company_id,
            )
        )
        rule = result.scalar_one_or_none()
        if not rule:
            raise HTTPException(404,"Safety rule not found")
        await session.delete(rule)
        await session.flush()
        return {"message": f"Safety rule #{rule_id} deleted"}


# ── Admin CRUD — Escalation ────────────────────────────────────────

class EscalationLevelRequest(BaseModel):
    level: int
    name: str
    description: str = ""


@app.post("/api/admin/escalation-levels")
async def create_escalation_level(req: EscalationLevelRequest,admin: TokenData = Depends(require_company_admin)):
    """Create an escalation level (admin only,scoped).

    After saving,re-runs escalation_agent on any incidents that were parked
    in PENDING_ESCALATION_CONFIG status,now that a matrix exists.
    """
    try:
        async with get_session() as session:
            lvl = EscalationLevel(
                company_id=admin.company_id,
                level=req.level,name=req.name,description=req.description or "",
            )
            session.add(lvl)
            await session.flush()
    except IntegrityError:
        raise HTTPException(400,f"Escalation level {req.level} already exists for this organization.")
    except Exception as e:
        logger.warning("Create escalation level failed: %s",e,exc_info=True)
        raise HTTPException(500,"Failed to create escalation level. Check that migrations have been applied.")

    # Background: re-process incidents that were waiting for escalation config
    asyncio.create_task(_safe_background(_reprocess_pending_escalations(admin.company_id)))
    return {"message": f"Escalation level {req.level} created"}


@app.put("/api/admin/escalation-levels/{level_id}")
async def update_escalation_level(level_id: int,req: EscalationLevelRequest,admin: TokenData = Depends(require_company_admin)):
    """Update an escalation level (admin only). level_id is the level number (composite PK with company_id)."""
    async with get_session() as session:
        lvl = await session.get(EscalationLevel,(admin.company_id,level_id))
        if not lvl:
            raise HTTPException(404,"Escalation level not found")

        lvl.name = req.name
        lvl.description = req.description
        await session.flush()
        return {"message": f"Escalation level {level_id} updated"}


@app.delete("/api/admin/escalation-levels/{level_id}")
async def delete_escalation_level(level_id: int,admin: TokenData = Depends(require_company_admin)):
    """Delete an escalation level (admin only). level_id is the level number (composite PK with company_id)."""
    async with get_session() as session:
        lvl = await session.get(EscalationLevel,(admin.company_id,level_id))
        if not lvl:
            raise HTTPException(404,"Escalation level not found")
        # EC3: prevent deletion if users still have this escalation type
        user_type_code = f"L{level_id}"
        assigned_count = await session.scalar(
            sa_select(func.count()).select_from(User).where(
                User.company_id == admin.company_id,
                User.user_type == user_type_code,
                User.is_active.is_(True),
            )
        ) or 0
        if assigned_count > 0:
            raise HTTPException(
                409,
                f"Cannot delete level L{level_id}: {assigned_count} active user(s) still assigned. "
                f"Reassign them first.",
            )
        await session.delete(lvl)
        await session.flush()
        return {"message": f"Escalation level {level_id} deleted"}


class EscalationRuleRequest(BaseModel):
    condition: str
    confidence_min: float = 0.0
    confidence_max: float = 1.0
    safety_impact: str = "low"
    escalation_level: int = 1
    description: str = ""
    sort_order: int = 100


@app.post("/api/admin/escalation-rules")
async def create_escalation_rule(req: EscalationRuleRequest,admin: TokenData = Depends(require_company_admin)):
    """Create an escalation rule (admin only,scoped)."""
    async with get_session() as session:
        rule = EscalationRule(
            company_id=admin.company_id,
            condition=req.condition,
            confidence_min=req.confidence_min,
            confidence_max=req.confidence_max,
            safety_impact=req.safety_impact.lower(),
            escalation_level=req.escalation_level,
            description=req.description,
            sort_order=req.sort_order,
        )
        session.add(rule)
        await session.flush()

        return {"message": "Escalation rule created","rule": {"id": rule.id,"condition": rule.condition}}


@app.put("/api/admin/escalation-rules/{rule_id}")
async def update_escalation_rule(rule_id: int,req: EscalationRuleRequest,admin: TokenData = Depends(require_company_admin)):
    """Update an escalation rule (admin only)."""
    async with get_session() as session:
        rule = await session.get(EscalationRule,rule_id)
        if not rule:
            raise HTTPException(404,"Escalation rule not found")

        rule.condition = req.condition
        rule.confidence_min = req.confidence_min
        rule.confidence_max = req.confidence_max
        rule.safety_impact = req.safety_impact.lower()
        rule.escalation_level = req.escalation_level
        rule.description = req.description
        rule.sort_order = req.sort_order

        await session.flush()
        return {"message": f"Escalation rule #{rule_id} updated"}


@app.delete("/api/admin/escalation-rules/{rule_id}")
async def delete_escalation_rule(rule_id: int,admin: TokenData = Depends(require_company_admin)):
    """Delete an escalation rule (admin only)."""
    async with get_session() as session:
        rule = await session.get(EscalationRule,rule_id)
        if not rule:
            raise HTTPException(404,"Escalation rule not found")
        await session.delete(rule)
        await session.flush()
        return {"message": f"Escalation rule #{rule_id} deleted"}


# ── Auth & Admin API ────────────────────────────────────────────────
from src.db.models import User


class LoginRequest(BaseModel):
    """Login with email and/or username. At least one of email or username required."""
    email: Optional[str] = None
    username: Optional[str] = None
    password: str

    def get_identifier(self) -> str | None:
        """Return the value to use for lookup (email preferred)."""
        if self.email and self.email.strip():
            return self.email.strip()
        if self.username and self.username.strip():
            return self.username.strip()
        return None


class RegisterRequest(BaseModel):
    username: str = Field(...,min_length=2,max_length=100)
    email: str = Field(...,min_length=5,max_length=255)
    password: str = Field(...,min_length=8,max_length=128)
    full_name: str = Field(default="",max_length=200)
    user_type: str = Field(default="operator",max_length=30)


class UpdateUserRequest(BaseModel):
    email: Optional[str] = Field(default=None,max_length=255)
    full_name: Optional[str] = Field(default=None,max_length=200)
    user_type: Optional[str] = Field(default=None,max_length=30)
    is_active: Optional[bool] = None
    password: Optional[str] = Field(default=None,min_length=8,max_length=128)


def _user_to_dict(u: User) -> dict:
    d = {
        "id": u.id,
        "company_id": u.company_id,
        "username": u.username,
        "email": u.email,
        "full_name": u.full_name,
        "user_type": u.user_type,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else "",
    }
    if u.user_type and u.user_type.startswith("L"):
        try:
            level_num = int(u.user_type[1:])
            from src.data.escalation_matrix import get_escalation_levels
            levels = get_escalation_levels(company_id=u.company_id)
            if levels and level_num in levels:
                d["escalation_level_name"] = levels[level_num].get("name","")
        except Exception:
            pass
    return d


@app.post("/api/auth/login")
async def login(req: LoginRequest):
    """Authenticate user and return JWT token. Accepts email or username."""
    identifier = req.get_identifier()
    if not identifier:
        raise HTTPException(status_code=422,detail="Email or username is required")

    async with get_session() as session:
        result = await session.execute(
            sa_select(User).where(
                (User.email == identifier) | (User.username == identifier)
            )
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(req.password,user.hashed_password):
            raise HTTPException(status_code=401,detail="Invalid email or password")

        if not user.is_active:
            raise HTTPException(status_code=403,detail="Account is deactivated")

        token = create_access_token({
            "user_id": user.id,
            "username": user.username,
            "user_type": user.user_type,
            "company_id": user.company_id,
        })

        return {
            "access_token": token,
            "token_type": "bearer",
            "user": _user_to_dict(user),
        }


@app.post("/api/auth/register")
async def register_first_admin(req: RegisterRequest):
    """Register the first user (bootstrap only — fails if users exist).
    Creates a super_admin. Super admin can then create companies and
    admin users for each company via /api/super-admin/."""
    async with get_session() as session:
        count = await session.scalar(
            sa_select(func.count()).select_from(User)
        )
        if count >  0:
            raise HTTPException(400,"Users already exist — use admin portal to create new users")

        user = User(
            company_id=None, # super_admin has no company
            username=req.username,
            email=req.email,
            hashed_password=hash_password(req.password),
            full_name=req.full_name,
            user_type="super_admin",
            is_active=True,
        )
        session.add(user)
        await session.flush()

        token = create_access_token({
            "user_id": user.id,
            "username": user.username,
            "user_type": "super_admin",
            "company_id": None,
        })

        return {
            "access_token": token,
            "token_type": "bearer",
            "user": _user_to_dict(user),
            "message": "Super admin account created. Use /api/super-admin/ to create companies and company admins.",
        }


@app.get("/api/auth/me")
async def get_me(user: TokenData = Depends(require_auth)):
    """Get current authenticated user's info."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(User).where(User.id == user.user_id)
        )
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(404,"User not found")
        return _user_to_dict(db_user)


# ── Admin User Management ──────────────────────────────────────────

@app.get("/api/admin/users")
async def list_users(admin: TokenData = Depends(require_company_admin)):
    """List users in admin's company."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(User)
            .where(User.company_id == admin.company_id)
            .order_by(User.created_at)
        )
        users = result.scalars().all()
        return {"users": [_user_to_dict(u) for u in users]}


async def _allowed_user_types_for_company(session,company_id: int) -> set[str]:
    """Return valid user_type values: standard USER_TYPES plus escalation level codes (L1,L2,...) for this company."""
    allowed = set(USER_TYPES)
    result = await session.execute(
        sa_select(EscalationLevel.level).where(EscalationLevel.company_id == company_id)
    )
    for (level,) in result.all():
        allowed.add(f"L{level}")
    return allowed


@app.post("/api/admin/users")
async def create_user(req: RegisterRequest,admin: TokenData = Depends(require_company_admin)):
    """Create a new user (company admin only — scoped to admin's company). Cannot create super_admin. User type can be standard or from escalation levels (L1,L2,...)."""
    if req.user_type == "super_admin":
        raise HTTPException(403,"Only a super admin can create another super admin")

    async with get_session() as session:
        allowed = await _allowed_user_types_for_company(session,admin.company_id)
        if req.user_type not in allowed:
            raise HTTPException(400,f"Invalid user type. Must be one of: {sorted(allowed)}")
        # Check uniqueness
        existing = await session.execute(
            sa_select(User).where(
                (User.username == req.username) | (User.email == req.email)
            )
        )
        if existing.first():
            raise HTTPException(409,"Username or email already exists")

        user = User(
            company_id=admin.company_id,
            username=req.username,
            email=req.email,
            hashed_password=hash_password(req.password),
            full_name=req.full_name,
            user_type=req.user_type,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        return {"user": _user_to_dict(user),"message": "User created successfully"}


@app.put("/api/admin/users/{user_id}")
async def update_user(user_id: int,req: UpdateUserRequest,admin: TokenData = Depends(require_company_admin)):
    """Update a user (admin only,scoped to admin's company)."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(User)
            .where(User.id == user_id)
            .where(User.company_id == admin.company_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(404,"User not found")

        if req.email is not None:
            user.email = req.email
        if req.full_name is not None:
            user.full_name = req.full_name
        if req.user_type is not None:
            allowed = await _allowed_user_types_for_company(session,admin.company_id)
            if req.user_type not in allowed:
                raise HTTPException(400,f"Invalid user type. Must be one of: {sorted(allowed)}")
            user.user_type = req.user_type
        if req.is_active is not None:
            user.is_active = req.is_active
        if req.password is not None:
            user.hashed_password = hash_password(req.password)

        await session.flush()
        return {"user": _user_to_dict(user),"message": "User updated"}


@app.delete("/api/admin/users/{user_id}")
async def delete_user(user_id: int,admin: TokenData = Depends(require_company_admin)):
    """Deactivate a user (admin only). Does not hard-delete."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(User)
            .where(User.id == user_id)
            .where(User.company_id == admin.company_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(404,"User not found")

        if user.id == admin.user_id:
            raise HTTPException(400,"Cannot deactivate yourself")

        user.is_active = False
        await session.flush()
        return {"message": f"User '{user.username}' deactivated"}


# ── Admin Dashboard ─────────────────────────────────────────────────

from sqlalchemy import func


def _safe_round(val,ndigits=1):
    """Return rounded number or None; avoid TypeError for None or non-numeric."""
    if val is None:
        return None
    try:
        return round(float(val),ndigits)
    except (TypeError,ValueError):
        return None


@app.get("/api/admin/dashboard")
async def admin_dashboard(admin: TokenData = Depends(require_company_admin)):
    """Dashboard stats for admin portal (scoped to company). Returns zeros if DB empty or schema missing."""
    cid = admin.company_id
    fallback = {
        "total_incidents": 0,
        "open_incidents": 0,
        "closed_incidents": 0,
        "total_users": 0,
        "total_equipment": 0,
        "total_safety_rules": 0,
        "total_reports": 0,
        "avg_mttd_seconds": None,
    }
    try:
        async with get_session() as session:
            total_incidents = await session.scalar(
                sa_select(func.count()).select_from(Incident).where(Incident.company_id == cid)
            ) or 0

            open_incidents = await session.scalar(
                sa_select(func.count()).select_from(Incident).where(
                    Incident.company_id == cid,Incident.status != "CLOSED"
                )
            ) or 0

            total_users = await session.scalar(
                sa_select(func.count()).select_from(User).where(User.company_id == cid)
            ) or 0

            total_equipment = await session.scalar(
                sa_select(func.count()).select_from(Equipment).where(Equipment.company_id == cid)
            ) or 0

            total_safety_rules = await session.scalar(
                sa_select(func.count()).select_from(SafetyRule).where(SafetyRule.company_id == cid)
            ) or 0

            total_reports = await session.scalar(
                sa_select(func.count()).select_from(IncidentReport).where(IncidentReport.company_id == cid)
            ) or 0

            avg_mttd = await session.scalar(
                sa_select(func.avg(Incident.mttd_seconds)).where(
                    Incident.company_id == cid,Incident.mttd_seconds.isnot(None)
                )
            )

            return {
                "total_incidents": total_incidents,
                "open_incidents": open_incidents,
                "closed_incidents": total_incidents - open_incidents,
                "total_users": total_users,
                "total_equipment": total_equipment,
                "total_safety_rules": total_safety_rules,
                "total_reports": total_reports,
                "avg_mttd_seconds": _safe_round(avg_mttd),
            }
    except Exception as e:
        logger.warning("Dashboard stats failed (e.g. missing company_id columns): %s",e,exc_info=True)
        return fallback


# ── Password Change ────────────────────────────────────────────────

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(...,min_length=8,max_length=128)


@app.put("/api/auth/change-password")
async def change_password(req: ChangePasswordRequest,user: TokenData = Depends(require_auth)):
    """Change the current user's password."""
    async with get_session() as session:
        db_user = await session.get(User,user.user_id)
        if not db_user:
            raise HTTPException(404,"User not found")

        if not verify_password(req.current_password,db_user.hashed_password):
            raise HTTPException(400,"Current password is incorrect")

        db_user.hashed_password = hash_password(req.new_password)
        await session.flush()
        return {"message": "Password changed successfully"}


# ── KPI Stats ──────────────────────────────────────────────────────

@app.get("/api/admin/stats/kpis")
async def get_kpi_stats(admin: TokenData = Depends(require_company_admin)):
    """Get KPI statistics (§27): MTTD,escalation rate,process failure rate. Returns zeros if DB empty or schema missing."""
    fallback = {
        "mttd": {"average_seconds": None,"min_seconds": None,"max_seconds": None},
        "incidents": {"total": 0,"escalated": 0,"closed": 0,"escalation_rate_pct": 0.0},
        "process_failures": {"count": 0,"total_reports": 0,"detection_rate_pct": 0.0},
    }
    try:
        async with get_session() as session:
            total_incidents = await session.scalar(
                sa_select(func.count()).select_from(Incident).where(Incident.company_id == admin.company_id)
            ) or 0

            mttd_filter = (Incident.company_id == admin.company_id) & Incident.mttd_seconds.isnot(None)
            avg_mttd = await session.scalar(
                sa_select(func.avg(Incident.mttd_seconds)).where(mttd_filter)
            )
            min_mttd = await session.scalar(
                sa_select(func.min(Incident.mttd_seconds)).where(mttd_filter)
            )
            max_mttd = await session.scalar(
                sa_select(func.max(Incident.mttd_seconds)).where(mttd_filter)
            )

            escalated = await session.scalar(
                sa_select(func.count()).select_from(Incident).where(
                    Incident.company_id == admin.company_id,Incident.status == "ESCALATED"
                )
            ) or 0

            closed = await session.scalar(
                sa_select(func.count()).select_from(Incident).where(
                    Incident.company_id == admin.company_id,Incident.status == "CLOSED"
                )
            ) or 0

            process_failures = await session.scalar(
                sa_select(func.count()).select_from(IncidentReport).where(
                    IncidentReport.company_id == admin.company_id,
                    IncidentReport.root_cause_category == "process",
                )
            ) or 0

            total_reports = await session.scalar(
                sa_select(func.count()).select_from(IncidentReport).where(
                    IncidentReport.company_id == admin.company_id
                )
            ) or 0

            escalation_rate = round(escalated / max(total_incidents,1) * 100,1)
            process_failure_rate = round(process_failures / max(total_reports,1) * 100,1)

            return {
                "mttd": {
                    "average_seconds": _safe_round(avg_mttd),
                    "min_seconds": _safe_round(min_mttd),
                    "max_seconds": _safe_round(max_mttd),
                },
                "incidents": {
                    "total": total_incidents,
                    "escalated": escalated,
                    "closed": closed,
                    "escalation_rate_pct": escalation_rate,
                },
                "process_failures": {
                    "count": process_failures,
                    "total_reports": total_reports,
                    "detection_rate_pct": process_failure_rate,
                },
            }
    except Exception as e:
        logger.warning("KPI stats failed (e.g. missing company_id columns): %s",e,exc_info=True)
        return fallback


# ── Super Admin API (create companies & company admins) ──────────────

class CompanyRequest(BaseModel):
    name: str


class CreateCompanyAdminRequest(BaseModel):
    """Request body for creating a company admin (super_admin only)."""
    username: str
    email: str
    password: str = Field(...,min_length=8,max_length=128)
    full_name: str = ""


@app.get("/api/super-admin/companies")
async def super_admin_list_companies(super_admin: TokenData = Depends(require_super_admin)):
    """List all companies (super_admin only)."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(Company).order_by(Company.id)
        )
        companies = result.scalars().all()
        return {
            "companies": [
                {
                    "id": c.id,
                    "name": c.name,
                    "is_active": c.is_active,
                    "created_at": c.created_at.isoformat() if c.created_at else "",
                }
                for c in companies
            ]
        }


@app.get("/api/super-admin/admins")
async def super_admin_list_admins(super_admin: TokenData = Depends(require_super_admin)):
    """List all admin users across all companies (super_admin only)."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(User,Company.name.label("company_name"))
            .outerjoin(Company,User.company_id == Company.id)
            .where(User.user_type == "admin")
            .order_by(Company.id.nulls_last(),User.id)
        )
        rows = result.all()
        return {
            "admins": [
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "full_name": u.full_name,
                    "user_type": u.user_type,
                    "is_active": u.is_active,
                    "company_id": u.company_id,
                    "company_name": company_name or "—",
                    "created_at": u.created_at.isoformat() if u.created_at else "",
                }
                for u,company_name in rows
            ]
        }


@app.post("/api/super-admin/companies")
async def super_admin_create_company(req: CompanyRequest,super_admin: TokenData = Depends(require_super_admin)):
    """Create a new company (super_admin only)."""
    async with get_session() as session:
        existing = await session.execute(
            sa_select(Company).where(
                Company.name == req.name
            )
        )
        if existing.first():
            raise HTTPException(409,"Company name already exists")

        company = Company(
            name=req.name,
            is_active=True,
        )
        session.add(company)
        await session.flush()

        return {
            "company": {
                "id": company.id,
                "name": company.name,
            },
            "message": "Company created successfully",
        }


@app.put("/api/super-admin/companies/{company_id}")
async def super_admin_update_company(
    company_id: int,
    req: CompanyRequest,
    super_admin: TokenData = Depends(require_super_admin),
):
    """Update a company name (super_admin only)."""
    async with get_session() as session:
        company = await session.get(Company,company_id)
        if not company:
            raise HTTPException(404,"Company not found")
        existing = await session.execute(
            sa_select(Company).where(
                Company.id != company_id,
                Company.name == req.name,
            )
        )
        if existing.first():
            raise HTTPException(409,"Company name already in use by another company")
        company.name = req.name.strip()
        await session.flush()
        return {
            "company": {"id": company.id,"name": company.name,},
            "message": "Company updated successfully",
        }


class UpdateCompanyAdminRequest(BaseModel):
    """Request body for updating a company admin (super_admin only)."""
    company_id: Optional[int] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    password: Optional[str] = Field(default=None,min_length=8,max_length=128)


@app.put("/api/super-admin/admins/{user_id}")
async def super_admin_update_admin(
    user_id: int,
    req: UpdateCompanyAdminRequest,
    super_admin: TokenData = Depends(require_super_admin),
):
    """Update a company admin's organization,email,full_name,or password (super_admin only). One admin per company."""
    async with get_session() as session:
        target = await session.get(User,user_id)
        if not target:
            raise HTTPException(404,"User not found")
        if target.user_type != "admin":
            raise HTTPException(400,"Only company admins can be updated this way")
        if req.company_id is not None:
            company = await session.get(Company,req.company_id)
            if not company:
                raise HTTPException(404,"Company not found")
            # One admin per company: target company must not have another admin
            other = await session.execute(
                sa_select(User).where(
                    User.company_id == req.company_id,
                    User.user_type == "admin",
                    User.id != user_id,
                )
            )
            if other.first():
                raise HTTPException(409,"That company already has an admin. One admin per company.")
            target.company_id = req.company_id
        if req.email is not None and req.email.strip():
            existing = await session.execute(sa_select(User).where(User.email == req.email.strip(),User.id != user_id))
            if existing.scalar_one_or_none():
                raise HTTPException(409,"Email already in use")
            target.email = req.email.strip()
        if req.full_name is not None:
            target.full_name = req.full_name.strip()
        if req.password is not None:
            target.hashed_password = hash_password(req.password)
        await session.flush()
        return {"user": _user_to_dict(target),"message": "Admin updated successfully"}


@app.post("/api/super-admin/companies/{company_id}/admins")
async def super_admin_create_company_admin(
    company_id: int,
    req: CreateCompanyAdminRequest,
    super_admin: TokenData = Depends(require_super_admin),
):
    """Create an admin user for a company (super_admin only). One admin per company."""
    async with get_session() as session:
        company = await session.get(Company,company_id)
        if not company:
            raise HTTPException(404,"Company not found")

        # One admin per company
        existing_admin = await session.execute(
            sa_select(User).where(User.company_id == company_id,User.user_type == "admin")
        )
        if existing_admin.first():
            raise HTTPException(409,"This company already has an admin. One admin per company. Edit the existing admin to change organization.")

        existing = await session.execute(
            sa_select(User).where(
                (User.username == req.username) | (User.email == req.email)
            )
        )
        if existing.first():
            raise HTTPException(409,"Username or email already exists")

        user = User(
            company_id=company_id,
            username=req.username,
            email=req.email,
            hashed_password=hash_password(req.password),
            full_name=req.full_name,
            user_type="admin",
            is_active=True,
        )
        session.add(user)
        await session.flush()

        # When a new admin is assigned,activate all users of this company
        await session.execute(
            sa_update(User).where(User.company_id == company_id).values(is_active=True)
        )
        await session.flush()

        return {
            "user": _user_to_dict(user),
            "message": f"Admin created for company '{company.name}'",
        }


@app.post("/api/super-admin/admins/{user_id}/deactivate")
async def super_admin_deactivate_admin(
    user_id: int,
    super_admin: TokenData = Depends(require_super_admin),
):
    """Delete the admin user and deactivate all other users in the same company (super_admin only)."""
    async with get_session() as session:
        target = await session.get(User,user_id)
        if not target:
            raise HTTPException(404,"User not found")
        if target.user_type != "admin":
            raise HTTPException(400,"Only company admins can be removed this way")
        cid = target.company_id
        if not cid:
            raise HTTPException(400,"User has no company")

        # Deactivate all other users in this company (excluding the admin we are deleting)
        await session.execute(
            sa_update(User).where(User.company_id == cid,User.id != user_id).values(is_active=False)
        )
        await session.flush()
        # Delete the admin user
        await session.delete(target)
        await session.flush()
        return {
            "message": "Admin removed and all other users in the company deactivated.",
        }


@app.post("/api/super-admin/companies/{company_id}/deactivate")
async def super_admin_deactivate_company(
    company_id: int,
    super_admin: TokenData = Depends(require_super_admin),
):
    """Deactivate a company and all its users (super_admin only). No data deleted."""
    async with get_session() as session:
        company = await session.get(Company,company_id)
        if not company:
            raise HTTPException(404,"Company not found")
        await session.execute(
            sa_update(Company).where(Company.id == company_id).values(is_active=False)
        )
        await session.execute(
            sa_update(User).where(User.company_id == company_id).values(is_active=False)
        )
        await session.flush()
        return {"message": f"Company '{company.name}' and all its users have been deactivated."}


@app.post("/api/super-admin/companies/{company_id}/activate")
async def super_admin_activate_company(
    company_id: int,
    super_admin: TokenData = Depends(require_super_admin),
):
    """Activate a company and all its users (super_admin only)."""
    async with get_session() as session:
        company = await session.get(Company,company_id)
        if not company:
            raise HTTPException(404,"Company not found")
        await session.execute(
            sa_update(Company).where(Company.id == company_id).values(is_active=True)
        )
        await session.execute(
            sa_update(User).where(User.company_id == company_id).values(is_active=True)
        )
        await session.flush()
        return {"message": f"Company '{company.name}' and all its users have been activated."}


# ── Company Management API ─────────────────────────────────────────


@app.get("/api/admin/companies")
async def list_companies(admin: TokenData = Depends(require_admin)):
    """List all companies (admin only)."""
    async with get_session() as session:
        result = await session.execute(
            sa_select(Company).order_by(Company.id)
        )
        companies = result.scalars().all()
        return {
            "companies": [
                {
                    "id": c.id,
                    "name": c.name,
                    "is_active": c.is_active,
                    "created_at": c.created_at.isoformat() if c.created_at else "",
                }
                for c in companies
            ]
        }


@app.post("/api/admin/companies")
async def create_company(req: CompanyRequest,admin: TokenData = Depends(require_admin)):
    """Create a new company (admin only)."""
    async with get_session() as session:
        existing = await session.execute(
            sa_select(Company).where(
                Company.name == req.name
            )
        )
        if existing.first():
            raise HTTPException(409,"Company name already exists")

        company = Company(
            name=req.name,
            is_active=True,
        )
        session.add(company)
        await session.flush()

        # EC2: Auto-create a default L1 escalation level
        default_level = EscalationLevel(
            company_id=company.id,
            level=1,
            name="Shift Manager",
            description="Default escalation level for shift managers",
        )
        session.add(default_level)
        await session.flush()

        return {
            "company": {
                "id": company.id,
                "name": company.name,
            },
            "message": "Company created successfully",
        }


@app.get("/api/companies/current")
async def get_current_company(user: TokenData = Depends(require_auth)):
    """Get the current user's company info. Super admin has no company."""
    if user.company_id is None:
        raise HTTPException(404,"Super admin has no company.")
    async with get_session() as session:
        company = await session.get(Company,user.company_id)
        if not company:
            raise HTTPException(404,"Company not found")
        return {
            "id": company.id,
            "name": company.name,
            "is_active": company.is_active,
        }


# ── Serve React frontend ────────────────────────────────────────────

import os
from fastapi.responses import FileResponse

frontend_dist = os.path.join(os.path.dirname(__file__),"frontend","dist")
if os.path.exists(frontend_dist):
    # Serve static assets (JS,CSS,images,etc.)
    assets_dir = os.path.join(frontend_dist,"assets")
    if os.path.exists(assets_dir):
        app.mount("/assets",StaticFiles(directory=assets_dir),name="static_assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Catch-all: serve static files or index.html for non-API routes (SPA).

        Unregistered ``/api/...`` paths must not return HTML 200 — API clients
        need a JSON 404. FastAPI only reaches this handler when no API route
        matched.
        """
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(
                status_code=404,
                detail={"error": "not_found","path": f"/{full_path}"},
            )
        # Try to serve the exact file first (e.g. favicon.ico,vite.svg)
        file_path = os.path.join(frontend_dist,full_path)
        if full_path and os.path.isfile(file_path):
            return FileResponse(file_path)
        # Otherwise,serve index.html and let React Router handle routing
        return FileResponse(os.path.join(frontend_dist,"index.html"))


# ── Run ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app,host="0.0.0.0",port=8020)
