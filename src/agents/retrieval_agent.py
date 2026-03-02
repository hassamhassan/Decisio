"""
Decisio — Retrieval Agent (Decision Memory)

Retrieves similar past incidents and verified decision patterns
using Qdrant vector search.  (§6.3 of the guide).

In-memory Qdrant is used for development; production should use
a persistent Qdrant server with tenant-isolated namespaces.
"""

from __future__ import annotations

import os
import logging

from src.state.state import DecisioState, RetrievedPattern

logger = logging.getLogger(__name__)

# ── Qdrant helpers ──────────────────────────────────────────────────
# Embedding model: BGE base English v1.5 (MTEB top tier, 768d, sentence-transformers)
EMBEDDING_MODEL = "BAAI/bge-base-en-v1.5"
EMBEDDING_DIMENSION = 768

_qdrant_client = None
_collection_name = "decisio_patterns"


def _get_qdrant():
    """Lazy-init an in-memory Qdrant client for development."""
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client

    # --- DISABLED: vector store load (uncomment to enable Qdrant retrieval) ---
    # try:
    #     from qdrant_client import QdrantClient
    #     from qdrant_client.models import Distance, VectorParams
    #
    #     qdrant_url = os.getenv("QDRANT_URL", "").strip()
    #     if qdrant_url:
    #         _qdrant_client = QdrantClient(url=qdrant_url)
    #     else:
    #         _qdrant_client = QdrantClient(":memory:")
    #
    #     collections = [c.name for c in _qdrant_client.get_collections().collections]
    #     if _collection_name not in collections:
    #         _qdrant_client.create_collection(
    #             collection_name=_collection_name,
    #             vectors_config=VectorParams(size=EMBEDDING_DIMENSION, distance=Distance.COSINE),
    #         )
    #         try:
    #             from qdrant_client.models import PayloadSchemaType
    #             _qdrant_client.create_payload_index(
    #                 collection_name=_collection_name,
    #                 field_name="company_id",
    #                 field_schema=PayloadSchemaType.INTEGER,
    #             )
    #         except Exception:
    #             pass
    #     return _qdrant_client
    # except Exception as e:
    #     logger.warning(f"Qdrant not available: {e}. Retrieval will use LLM fallback.")
    #     return None
    return None


def _get_embedder():
    """Lazy-load sentence-transformers model (BGE base en v1.5)."""
    # --- DISABLED: embedding model load (uncomment to enable vector retrieval) ---
    # try:
    #     from sentence_transformers import SentenceTransformer
    #     return SentenceTransformer(EMBEDDING_MODEL)
    # except Exception:
    #     return None
    return None




# ── Agent function ──────────────────────────────────────────────────

# Minimum similarity score to consider a pattern relevant
MIN_SIMILARITY_THRESHOLD = 0.6


def retrieval_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Retrieval Agent.

    Queries Qdrant for similar past incidents. If the vector store is
    empty or no results are similar enough, returns an empty list and
    lets downstream agents (Hypothesis, Safety, Decision Brief) reason
    purely via LLM — no fake/fabricated patterns are injected.
    """
    if state is None:
        state = {}
    incident_card = state.get("incident_card") or {}
    if not incident_card:
        return {"retrieved_patterns": [], "current_node": "retrieval"}

    summary = incident_card.get("normalized_summary", incident_card.get("report", ""))
    symptoms = incident_card.get("symptoms", [])
    query_text = f"{summary}. Symptoms: {', '.join(symptoms)}"

    patterns: list[dict] = []

    # ── Get company_id for tenant-scoped retrieval ────────────────
    company_id = state.get("company_id")

    # Multi-tenant safety: when company_id is missing, do not return patterns from vector store
    # (could leak cross-tenant data). Use LLM-only reasoning.
    if company_id is None:
        logger.warning("company_id missing in state — skipping retrieval for isolation safety.")
        return {
            "retrieved_patterns": [],
            "retrieval_confidence": 0.0,
            "current_node": "retrieval",
            "status": "DIAGNOSING",
        }

    # --- DISABLED: vector store search (uncomment when _get_qdrant / _get_embedder are enabled) ---
    client = _get_qdrant()
    embedder = _get_embedder()

    # if client and embedder:
    #     try:
    #         collection_info = client.get_collection(_collection_name)
    #         point_count = collection_info.points_count
    #         if point_count == 0:
    #             logger.info("Decision Memory is empty — skipping retrieval, using LLM reasoning only.")
    #         else:
    #             vector = embedder.encode(query_text).tolist()
    #             search_filter = None
    #             if company_id is not None:
    #                 try:
    #                     from qdrant_client.models import Filter, FieldCondition, MatchValue
    #                     search_filter = Filter(
    #                         must=[FieldCondition(key="company_id", match=MatchValue(value=company_id))]
    #                     )
    #                 except ImportError:
    #                     logger.warning("Could not import Qdrant filter models — searching without tenant filter")
    #             try:
    #                 results = client.search(
    #                     collection_name=_collection_name,
    #                     query_vector=vector,
    #                     query_filter=search_filter,
    #                     limit=3,
    #                 )
    #             except AttributeError:
    #                 from qdrant_client.models import models as qdrant_models
    #                 results = client.query_points(
    #                     collection_name=_collection_name,
    #                     query=vector,
    #                     query_filter=search_filter,
    #                     limit=3,
    #                 ).points
    #             for hit in results:
    #                 if hit.score >= MIN_SIMILARITY_THRESHOLD:
    #                     p = RetrievedPattern(
    #                         pattern_id=str(hit.id),
    #                         title=hit.payload.get("title", ""),
    #                         similarity_score=round(hit.score, 3),
    #                         signals=hit.payload.get("signals", []),
    #                         decision_taken=hit.payload.get("decision_taken", ""),
    #                         must_escalate=hit.payload.get("must_escalate", False),
    #                     )
    #                     patterns.append(p.model_dump())
    #             if not patterns and results:
    #                 best_score = max(h.score for h in results)
    #                 logger.info(
    #                     f"No similar patterns found (best score: {best_score:.2f}, "
    #                     f"threshold: {MIN_SIMILARITY_THRESHOLD}). Using LLM reasoning only."
    #                 )
    #     except Exception as e:
    #         logger.warning(f"Qdrant search failed: {e}. Using LLM reasoning only.")
    # else:
    if not (client and embedder):
        logger.info("Qdrant/embedder not available — using LLM reasoning only.")

    # Check for mandatory escalation patterns (only from real matches)
    escalation_triggered = state.get("escalation_triggered", False)
    escalation_reasons = list(state.get("escalation_reasons") or [])
    risk_score = state.get("risk_score") if state.get("risk_score") is not None else 5.0

    for p in patterns:
        if p.get("must_escalate"):
            escalation_triggered = True
            escalation_reasons.append(
                f"Mandatory escalation pattern matched: {p.get('title', 'unknown')}"
            )

    # ── Gap 4: Recurrence detection (§9, §10) ───────────────────────
    # Check if any matched pattern involves the same asset — this
    # indicates the same failure has happened before recently.
    asset_id = (incident_card.get("asset_id") or "").lower().strip()
    recurrence_detected = False

    if asset_id and patterns:
        for p in patterns:
            pattern_title = p.get("title", "").lower()
            if asset_id in pattern_title or p.get("similarity_score", 0) >= 0.8:
                recurrence_detected = True
                risk_score = min(10.0, risk_score + 1.5)
                escalation_reasons.append(
                    f"Recurrence detected: similar pattern '{p.get('title', '')}' "
                    f"(similarity {p.get('similarity_score', 0):.0%}) — risk increased"
                )
                logger.info(f"Recurrence detected for asset {asset_id}: {p.get('title', '')}")
                break

    # If recurrence + high risk → auto-escalate
    if recurrence_detected and risk_score >= 7.0:
        escalation_triggered = True
        escalation_reasons.append("Recurring failure with high risk — auto-escalation triggered")

    # Calculate retrieval confidence (average similarity of matches)
    retrieval_confidence = 0.0
    if patterns:
        retrieval_confidence = sum(p.get("similarity_score", 0) for p in patterns) / len(patterns)

    return {
        "retrieved_patterns": patterns,
        "retrieval_confidence": round(retrieval_confidence, 3),
        "escalation_triggered": escalation_triggered,
        "escalation_reasons": escalation_reasons,
        "risk_score": risk_score,
        "current_node": "retrieval",
        "status": "DIAGNOSING",
    }

