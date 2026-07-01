"""
Reference Code Lookup Agent

Answers direct reference-code meaning queries before the diagnostic loop when
the operator is not also describing a live operational incident.
"""

from __future__ import annotations

import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.prompt_context import get_language_instruction
from src.llm import get_llm_fast
from src.services.reference_code_service import (
    CODE_LOOKUP_SYSTEM_PROMPT,
    build_code_lookup_query,
    build_grounded_answer_prompt,
    build_not_verified_answer,
    classify_reference_code_intent,
    extract_reference_codes,
    resolve_asset_id,
)
from src.state.state import DecisioState

logger = logging.getLogger(__name__)


def reference_code_lookup_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: look up reference code meaning and optionally continue diagnosis.

    Sets:
      - reference_code_answer
      - reference_code_trace
      - reference_code_lookup_complete (True → END graph; False → continue to questions)
    """
    if state is None:
        state = {}

    report = state.get("report") or ""
    incident_card = state.get("incident_card") or {}
    intent = classify_reference_code_intent(report)

    if intent == "none":
        return {"current_node": "reference_code_lookup"}

    codes = extract_reference_codes(report)
    if not codes:
        return {"current_node": "reference_code_lookup"}

    company_id = state.get("company_id")
    asset_id = resolve_asset_id(report, incident_card)
    query_text = build_code_lookup_query(report, codes)

    chunks: list[dict] = []
    trace: dict = {}
    try:
        from src.services.reference_service import retrieve_with_trace
        result = retrieve_with_trace(
            company_id=int(company_id) if company_id else 0,
            equipment_id=asset_id,
            query_text=query_text,
            limit=5,
        )
        chunks = result.get("chunks") or []
        trace = result.get("trace") or {}
    except Exception as e:
        logger.warning("Reference code retrieval failed: %s", e)

    if not chunks:
        answer = build_not_verified_answer(codes, asset_id)
    else:
        lang_instruction = get_language_instruction(state.get("language"))
        llm = get_llm_fast(temperature=0.1)
        prompt = build_grounded_answer_prompt(codes, asset_id, chunks, report)
        try:
            response = llm.invoke([
                SystemMessage(content=CODE_LOOKUP_SYSTEM_PROMPT + lang_instruction),
                HumanMessage(content=prompt),
            ])
            answer = (response.content or "").strip()
            if not answer:
                answer = build_not_verified_answer(codes, asset_id)
        except Exception as e:
            logger.warning("Reference code LLM answer failed: %s", e)
            answer = build_not_verified_answer(codes, asset_id)

    code_only = intent == "code_only"
    out: dict = {
        "reference_code_answer": answer,
        "reference_code_trace": trace,
        "reference_code_lookup_complete": code_only,
        "current_node": "reference_code_lookup",
    }
    if code_only:
        out["status"] = "CODE_LOOKUP_COMPLETE"
        out["questions"] = []
    return out
