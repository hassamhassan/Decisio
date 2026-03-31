"""
Decisio — Retrieval Agent (Decision Memory)

Retrieves similar past incidents and verified decision patterns
using Qdrant vector search.  (§6.3 of the guide).

Set QDRANT_URL for a persistent server; otherwise an in-memory instance
is used (single-process only). Set DECISIO_DISABLE_RETRIEVAL=1 to skip
loading embeddings/Qdrant (LLM-only mode).
"""

from __future__ import annotations

import os
import logging

from src.state.state import DecisioState, RetrievedPattern

logger = logging.getLogger(__name__)

# Gemini embedding model. Must match Qdrant collection vector size.
# Override:
# - DECISIO_EMBEDDING_MODEL=gemini-embedding-001
# - DECISIO_EMBEDDING_DIMENSION=768
EMBEDDING_MODEL = os.getenv("DECISIO_EMBEDDING_MODEL", "gemini-embedding-001")
# Gemini `gemini-embedding-001` supports 128–3072 dims; recommended include 768.
# We default to 768 to match the existing Qdrant collection in this repo.
DEFAULT_EMBEDDING_DIMENSION = 768
_embedding_dimension = None

_qdrant_client = None
_embedder = None
_collection_name = "decisio_patterns"


def _retrieval_enabled() -> bool:
    return os.getenv("DECISIO_DISABLE_RETRIEVAL", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def _get_qdrant():
    """Lazy-init Qdrant client (remote URL or in-memory for dev)."""
    global _qdrant_client
    if not _retrieval_enabled():
        return None
    if _qdrant_client is not None:
        return _qdrant_client

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        qdrant_url = os.getenv("QDRANT_URL", "").strip()
        if qdrant_url:
            _qdrant_client = QdrantClient(url=qdrant_url)
        else:
            _qdrant_client = QdrantClient(":memory:")

        collections = [c.name for c in _qdrant_client.get_collections().collections]
        if _collection_name not in collections:
            dim = _get_embedding_dimension(existing_client=_qdrant_client)
            _qdrant_client.create_collection(
                collection_name=_collection_name,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            try:
                from qdrant_client.models import PayloadSchemaType

                _qdrant_client.create_payload_index(
                    collection_name=_collection_name,
                    field_name="company_id",
                    field_schema=PayloadSchemaType.INTEGER,
                )
            except Exception:
                pass
        return _qdrant_client
    except Exception as e:
        logger.warning("Qdrant not available: %s. Retrieval disabled.", e)
        return None


def _get_embedding_dimension(*, existing_client=None) -> int:
    """
    Determine embedding dimension consistently across:
    - Qdrant collection vector size (if collection already exists)
    - Gemini embedding output_dimensionality
    - New collection creation
    """
    global _embedding_dimension
    if _embedding_dimension is not None:
        return _embedding_dimension

    # 1) If collection exists, prefer its configured size (prevents mismatch errors).
    client = existing_client or _qdrant_client
    if client is not None:
        try:
            col = client.get_collection(_collection_name)
            vectors = getattr(col.config.params, "vectors", None)
            if vectors is not None and hasattr(vectors, "size") and vectors.size:
                _embedding_dimension = int(vectors.size)
                return _embedding_dimension
        except Exception:
            pass

    # 2) Otherwise read from env, fallback to default.
    raw = os.getenv("DECISIO_EMBEDDING_DIMENSION", "").strip()
    if raw:
        try:
            _embedding_dimension = int(raw)
            return _embedding_dimension
        except ValueError:
            logger.warning("Invalid DECISIO_EMBEDDING_DIMENSION=%r; using default.", raw)

    _embedding_dimension = DEFAULT_EMBEDDING_DIMENSION
    return _embedding_dimension


def _get_embedder():
    """Lazy-load Gemini embeddings client."""
    global _embedder
    if not _retrieval_enabled():
        return None
    if _embedder is not None:
        return _embedder

    try:
        from google import genai
        from google.genai import types

        api_key = (
            os.getenv("GEMINI_API_KEY", "").strip()
            or os.getenv("GOOGLE_API_KEY", "").strip()
            or os.getenv("GENAI_API_KEY", "").strip()
        )
        if not api_key:
            raise RuntimeError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY/GENAI_API_KEY)")

        class _GeminiEmbedder:
            def __init__(self, *, key: str, model: str):
                self._client = genai.Client(api_key=key)
                self._model = model

            def encode(self, text: str):
                t = (text or "").strip() or " "
                t = t[:12_000]
                dim = _get_embedding_dimension()
                resp = self._client.models.embed_content(
                    model=self._model,
                    contents=t,
                    config=types.EmbedContentConfig(output_dimensionality=dim),
                )
                return resp.embeddings[0].values

        _embedder = _GeminiEmbedder(key=api_key, model=EMBEDDING_MODEL)
        logger.info("Loaded embedding model: %s (gemini)", EMBEDDING_MODEL)
        return _embedder
    except Exception as e:
        logger.warning("Embedding model not available: %s. Retrieval disabled.", e)
        return None


def _similarity_search(client, vector: list[float], search_filter, limit: int):
    """Run vector search; support legacy `search` and newer `query_points` APIs."""
    try:
        return client.search(
            collection_name=_collection_name,
            query_vector=vector,
            query_filter=search_filter,
            limit=limit,
        )
    except Exception:
        pass
    try:
        from qdrant_client.http import models as qmodels

        res = client.query_points(
            collection_name=_collection_name,
            query=qmodels.NearestQuery(nearest=vector),
            query_filter=search_filter,
            limit=limit,
            with_payload=True,
        )
        return list(res.points)
    except Exception:
        try:
            res = client.query_points(
                collection_name=_collection_name,
                query=vector,
                query_filter=search_filter,
                limit=limit,
                with_payload=True,
            )
            return list(res.points)
        except Exception as e:
            logger.warning("Qdrant search failed: %s", e)
            return []


# Minimum similarity score to consider a pattern relevant
MIN_SIMILARITY_THRESHOLD = 0.6
# Surface explicit “reuse prior decision” guidance when match is strong
MEMORY_GUIDANCE_THRESHOLD = 0.75


def _build_query_text(state: DecisioState) -> str:
    """Compose embedding text from incident + optional recent Q&A for richer matching."""
    incident_card = state.get("incident_card") or {}
    summary = incident_card.get("normalized_summary", incident_card.get("report", ""))
    symptoms = incident_card.get("symptoms", [])
    parts = [f"{summary}. Symptoms: {', '.join(symptoms) if symptoms else 'none'}"]
    qa_history = state.get("qa_history") or []
    if qa_history:
        tail = qa_history[-4:]
        bits = []
        for qa in tail:
            q = str(qa.get("question", ""))[:200]
            a = str(qa.get("answer", ""))[:200]
            if q or a:
                bits.append(f"Q: {q} A: {a}")
        if bits:
            parts.append("Recent diagnostics: " + " | ".join(bits))
    asset = (incident_card.get("asset_id") or "").strip()
    if asset:
        parts.append(f"Asset: {asset}")
    return " ".join(parts)


def retrieval_agent(state: DecisioState) -> DecisioState:
    """
    LangGraph node: Retrieval Agent.

    Queries Qdrant for similar past incidents (tenant-scoped). Populates
    `retrieved_patterns`, optional `memory_guidance` for strong matches,
    and may adjust escalation/risk for recurrence.
    """
    if state is None:
        state = {}
    incident_card = state.get("incident_card") or {}
    if not incident_card:
        return {
            "retrieved_patterns": [],
            "retrieval_confidence": 0.0,
            "memory_guidance": None,
            "current_node": "retrieval",
        }

    query_text = _build_query_text(state)
    patterns: list[dict] = []

    company_id = state.get("company_id")

    if company_id is None:
        logger.warning("company_id missing in state — skipping retrieval for isolation safety.")
        return {
            "retrieved_patterns": [],
            "retrieval_confidence": 0.0,
            "memory_guidance": None,
            "current_node": "retrieval",
            "status": "DIAGNOSING",
        }

    client = _get_qdrant()
    embedder = _get_embedder()

    if client and embedder:
        try:
            collection_info = client.get_collection(_collection_name)
            point_count = collection_info.points_count
            if point_count == 0:
                logger.info("Decision Memory is empty — no patterns to retrieve.")
            else:
                vec = embedder.encode(query_text)
                vector = vec.tolist() if hasattr(vec, "tolist") else list(vec)
                # Safety check: if Qdrant collection size doesn't match embedding dim, skip retrieval.
                try:
                    expected_dim = _get_embedding_dimension(existing_client=client)
                    if len(vector) != expected_dim:
                        logger.warning(
                            "Embedding dim mismatch (got=%s, expected=%s). Skipping retrieval.",
                            len(vector),
                            expected_dim,
                        )
                        return {
                            "retrieved_patterns": [],
                            "retrieval_confidence": 0.0,
                            "memory_guidance": None,
                            "current_node": "retrieval",
                            "status": "DIAGNOSING",
                        }
                except Exception:
                    pass
                search_filter = None
                try:
                    from qdrant_client.models import Filter, FieldCondition, MatchValue
                except ImportError:
                    logger.warning("Could not import Qdrant filter models — searching without tenant filter")
                else:
                    try:
                        cid = int(company_id)
                        search_filter = Filter(
                            must=[FieldCondition(key="company_id", match=MatchValue(value=cid))]
                        )
                    except (TypeError, ValueError):
                        logger.warning("Invalid company_id for retrieval filter: %s", company_id)
                        search_filter = None

                results = _similarity_search(client, vector, search_filter, limit=5)
                for hit in results:
                    score = float(getattr(hit, "score", 0) or 0)
                    if score < MIN_SIMILARITY_THRESHOLD:
                        continue
                    payload = getattr(hit, "payload", None) or {}
                    pid = getattr(hit, "id", "")
                    p = RetrievedPattern(
                        pattern_id=str(pid),
                        title=payload.get("title", ""),
                        similarity_score=round(score, 3),
                        signals=payload.get("signals", []) or [],
                        decision_taken=payload.get("decision_taken", "") or "",
                        must_escalate=bool(payload.get("must_escalate", False)),
                    )
                    patterns.append(p.model_dump())

                if not patterns and results:
                    best = max((float(getattr(h, "score", 0) or 0) for h in results), default=0.0)
                    logger.info(
                        "No patterns above similarity threshold (best=%.2f, min=%.2f).",
                        best,
                        MIN_SIMILARITY_THRESHOLD,
                    )
        except Exception as e:
            logger.warning("Qdrant search failed: %s. Using LLM reasoning only.", e)
    else:
        logger.debug("Qdrant/embedder not available — LLM-only reasoning.")

    memory_guidance = None
    if patterns:
        top = max(patterns, key=lambda x: x.get("similarity_score", 0))
        top_score = float(top.get("similarity_score", 0) or 0)
        if top_score >= MEMORY_GUIDANCE_THRESHOLD:
            title = top.get("title", "Similar case")
            decision = (top.get("decision_taken") or "").strip() or "(see stored pattern)"
            memory_guidance = (
                f"Decision Memory match ({top_score:.0%} similar): \"{title}\". "
                f"Prior verified outcome summary: {decision} "
                "Treat this as strong prior guidance—confirm it applies to the current field conditions before relying on it."
            )

    escalation_triggered = state.get("escalation_triggered", False)
    escalation_reasons = list(state.get("escalation_reasons") or [])
    risk_score = state.get("risk_score") if state.get("risk_score") is not None else 5.0

    for p in patterns:
        if p.get("must_escalate"):
            escalation_triggered = True
            escalation_reasons.append(
                f"Mandatory escalation pattern matched: {p.get('title', 'unknown')}"
            )

    asset_id = (incident_card.get("asset_id") or "").lower().strip()
    recurrence_detected = False

    if asset_id and patterns:
        for p in patterns:
            pattern_title = str(p.get("title", "")).lower()
            asset_match = len(asset_id) >= 3 and asset_id in pattern_title
            if asset_match or p.get("similarity_score", 0) >= 0.8:
                recurrence_detected = True
                risk_score = min(10.0, float(risk_score) + 1.5)
                escalation_reasons.append(
                    f"Recurrence detected: similar pattern '{p.get('title', '')}' "
                    f"(similarity {p.get('similarity_score', 0):.0%}) — risk increased"
                )
                logger.info("Recurrence detected for asset %s: %s", asset_id, p.get("title", ""))
                break

    # Recurrence increases risk and adds a reason, but does NOT auto-escalate by itself.
    # Escalation should be decided by the Safety agent (thresholds + blocks) or
    # explicit mandatory patterns (`must_escalate`).

    retrieval_confidence = 0.0
    if patterns:
        retrieval_confidence = sum(p.get("similarity_score", 0) for p in patterns) / len(patterns)

    return {
        "retrieved_patterns": patterns,
        "retrieval_confidence": round(retrieval_confidence, 3),
        "memory_guidance": memory_guidance,
        "escalation_triggered": escalation_triggered,
        "escalation_reasons": escalation_reasons,
        "risk_score": risk_score,
        "current_node": "retrieval",
        "status": "DIAGNOSING",
    }
