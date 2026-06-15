"""
Decisio — Knowledge Base Service

Handles embedding and Qdrant storage for admin-curated
problem/solution knowledge entries.

Each entry is stored in the `decisio_knowledge` Qdrant collection
as a single vector point embedding both the problem and solution text.

Metadata per point:
    {
        "company_id": int,
        "entry_id": str,       (UUID string of the DB row)
        "problem": str,
        "solution": str,
        "memory_type": "knowledge",
    }
"""

from __future__ import annotations

import os
import hashlib
import logging
import uuid
from typing import List

logger = logging.getLogger(__name__)

KNOWLEDGE_COLLECTION = "decisio_knowledge"

_qdrant_client = None
_embedder = None


def _get_qdrant():
    """Lazy-init Qdrant client and ensure the knowledge collection exists."""
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PayloadSchemaType

        qdrant_url = os.getenv("QDRANT_URL", "").strip()
        if qdrant_url:
            _qdrant_client = QdrantClient(url=qdrant_url)
        else:
            _qdrant_client = QdrantClient(":memory:")

        collections = [c.name for c in _qdrant_client.get_collections().collections]
        if KNOWLEDGE_COLLECTION not in collections:
            dim = _get_embedding_dimension()
            _qdrant_client.create_collection(
                collection_name=KNOWLEDGE_COLLECTION,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            for field, schema in [
                ("company_id", PayloadSchemaType.INTEGER),
                ("memory_type", PayloadSchemaType.KEYWORD),
            ]:
                try:
                    _qdrant_client.create_payload_index(
                        collection_name=KNOWLEDGE_COLLECTION,
                        field_name=field,
                        field_schema=schema,
                    )
                except Exception:
                    pass

        return _qdrant_client
    except Exception as e:
        logger.warning("Qdrant not available for knowledge service: %s", e)
        return None


def _get_embedder():
    """Lazy-load OpenAI embeddings client."""
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        from langchain_openai import OpenAIEmbeddings

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Missing OPENAI_API_KEY")

        class _Adapter:
            def __init__(self, key: str):
                model = os.getenv("DECISIO_EMBEDDING_MODEL", "text-embedding-3-small")
                self._client = OpenAIEmbeddings(api_key=key, model=model)

            def encode(self, text: str) -> list:
                t = (text or "").strip() or " "
                t = t[:32_000]
                vec = self._client.embed_query(t)
                return vec if isinstance(vec, list) else list(vec)

        _embedder = _Adapter(key=api_key)
        return _embedder
    except Exception as e:
        logger.warning("Embedder unavailable for knowledge service: %s", e)
        return None


def _get_embedding_dimension() -> int:
    raw = os.getenv("DECISIO_EMBEDDING_DIMENSION", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return 1536


def _point_id(company_id: int, entry_id: str) -> str:
    """Deterministic UUID from company + entry so we can overwrite on update."""
    key = f"{company_id}::{entry_id}"
    return str(uuid.UUID(hashlib.md5(key.encode()).hexdigest()))


def ingest_entry(
    company_id: int,
    entry_id: str,
    problem: str,
    solution: str,
    equipment_name: str | None = None,
) -> str:
    """
    Embed and upsert a knowledge entry into Qdrant.

    Returns the Qdrant point ID (deterministic UUID string).
    Raises RuntimeError if Qdrant or the embedder is unavailable.
    """
    client = _get_qdrant()
    embedder = _get_embedder()

    if client is None or embedder is None:
        raise RuntimeError("Qdrant or embedder is not available.")

    from qdrant_client.models import PointStruct

    machine_prefix = f"Machine: {equipment_name}\n" if equipment_name else ""
    text = f"{machine_prefix}Problem: {problem}\nSolution: {solution}"
    vector = embedder.encode(text)
    point_id = _point_id(company_id, entry_id)

    payload = {
        "company_id": int(company_id),
        "entry_id": str(entry_id),
        "problem": problem,
        "solution": solution,
        "memory_type": "knowledge",
    }
    if equipment_name:
        payload["equipment_name"] = equipment_name

    client.upsert(
        collection_name=KNOWLEDGE_COLLECTION,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload=payload,
            )
        ],
    )

    logger.info("Knowledge entry ingested: entry_id=%s company=%s equipment=%s", entry_id, company_id, equipment_name)
    return point_id


def delete_entry(company_id: int, entry_id: str) -> None:
    """Remove a knowledge entry from Qdrant by its deterministic point ID."""
    client = _get_qdrant()
    if client is None:
        logger.warning("delete_entry: Qdrant unavailable, skipping for entry_id=%s", entry_id)
        return

    point_id = _point_id(company_id, entry_id)
    try:
        client.delete(
            collection_name=KNOWLEDGE_COLLECTION,
            points_selector=[point_id],
        )
        logger.info("Knowledge entry deleted from Qdrant: entry_id=%s company=%s", entry_id, company_id)
    except Exception as e:
        logger.warning("Failed to delete knowledge entry from Qdrant: %s", e)


def list_chunks(company_id: int) -> List[dict]:
    """
    Scroll all knowledge points for this company from Qdrant.

    Returns a list of dicts with keys: entry_id, problem, solution, vector_id.
    Returns empty list if Qdrant is unavailable.
    """
    client = _get_qdrant()
    if client is None:
        return []

    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        scroll_filter = Filter(
            must=[
                FieldCondition(key="company_id", match=MatchValue(value=int(company_id))),
                FieldCondition(key="memory_type", match=MatchValue(value="knowledge")),
            ]
        )

        results = []
        offset = None
        while True:
            batch, next_offset = client.scroll(
                collection_name=KNOWLEDGE_COLLECTION,
                scroll_filter=scroll_filter,
                limit=100,
                offset=offset,
                with_payload=True,
            )
            for point in batch:
                payload = getattr(point, "payload", None) or {}
                results.append({
                    "entry_id": payload.get("entry_id", ""),
                    "problem": payload.get("problem", ""),
                    "solution": payload.get("solution", ""),
                    "vector_id": str(point.id),
                })
            if next_offset is None:
                break
            offset = next_offset

        return results
    except Exception as e:
        logger.warning("list_chunks failed for knowledge: %s", e)
        return []
