"""
Decisio — Unified Reference Sources Service

Handles ingestion, retrieval, and management of the `decisio_references`
Qdrant collection that backs the unified reference_sources table.

Replaces the separate manual_service and knowledge_service ingestion paths
for agent retrieval while leaving those services intact for legacy shims.

Qdrant chunk payload schema:
{
    "company_id": int,
    "reference_source_id": str,   # UUID
    "memory_type": "reference",
    "category": str,              # manual | document | sop | knowledge
    "source_type": str,           # text | file
    "source_filename": str,
    "title": str,
    "chunk_index": int,
    "text": str,
}

Scope resolution (retrieval):
    active_source_ids = reference_sources
        WHERE company_id = X AND status = 'active'
        AND (
            scope = 'company_wide'
            OR (scope = 'equipment_specific'
                AND EXISTS link WHERE equipment_id = <asset_id>)
        )
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import uuid
from functools import lru_cache
from typing import List

logger = logging.getLogger(__name__)

REFERENCES_COLLECTION = "decisio_references"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 200
SCORE_THRESHOLD = 0.3

_qdrant_client = None
_embedder = None


# ── Lazy singletons ──────────────────────────────────────────────────

def _get_qdrant():
    global _qdrant_client
    if _qdrant_client is not None:
        return _qdrant_client
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams, PayloadSchemaType

        qdrant_url = os.getenv("QDRANT_URL", "").strip()
        _qdrant_client = QdrantClient(url=qdrant_url) if qdrant_url else QdrantClient(":memory:")

        collections = [c.name for c in _qdrant_client.get_collections().collections]
        if REFERENCES_COLLECTION not in collections:
            dim = _get_embedding_dimension()
            _qdrant_client.create_collection(
                collection_name=REFERENCES_COLLECTION,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            for field, schema in [
                ("company_id", PayloadSchemaType.INTEGER),
                ("reference_source_id", PayloadSchemaType.KEYWORD),
                ("memory_type", PayloadSchemaType.KEYWORD),
            ]:
                try:
                    _qdrant_client.create_payload_index(
                        collection_name=REFERENCES_COLLECTION,
                        field_name=field,
                        field_schema=schema,
                    )
                except Exception:
                    pass

        return _qdrant_client
    except Exception as e:
        logger.warning("Qdrant not available for reference service: %s", e)
        return None


def _get_embedder():
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

            def encode_batch(self, texts: list[str]) -> list[list]:
                cleaned = [(t or "").strip() or " " for t in texts]
                cleaned = [t[:32_000] for t in cleaned]
                return self._client.embed_documents(cleaned)

        _embedder = _Adapter(key=api_key)
        return _embedder
    except Exception as e:
        logger.warning("Embedder unavailable for reference service: %s", e)
        return None


def _get_embedding_dimension() -> int:
    raw = os.getenv("DECISIO_EMBEDDING_DIMENSION", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return 1536


# ── Hashing ──────────────────────────────────────────────────────────

def compute_file_hash(content: bytes) -> str:
    """SHA-256 hex digest of raw file bytes."""
    return hashlib.sha256(content).hexdigest()


def compute_text_hash(problem: str, solution: str) -> str:
    """SHA-256 of canonical problem+solution text."""
    canonical = f"Problem:{(problem or '').strip()}\nSolution:{(solution or '').strip()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Text extraction (reused from manual_service pattern) ─────────────

def _extract_text_txt(content: bytes) -> str:
    try:
        return content.decode("utf-8", errors="replace")
    except Exception:
        return content.decode("latin-1", errors="replace")


def _extract_text_pdf(content: bytes) -> str:
    text = ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages).strip()
    except Exception:
        pass

    if not text:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
            text = "\n".join(pages).strip()
        except Exception:
            pass

    if not text:
        try:
            from pdfminer.high_level import extract_text as pdfminer_extract
            text = (pdfminer_extract(io.BytesIO(content)) or "").strip()
        except Exception:
            pass

    if not text:
        raise ValueError(
            "File contains no extractable text. "
            "The PDF may be a scanned image — please upload a text-based PDF, DOCX, or TXT file."
        )
    return text


def _extract_text_docx(content: bytes) -> str:
    try:
        import docx
        doc = docx.Document(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception as e:
        raise ValueError(f"DOCX parsing failed: {e}")


def extract_text(filename: str, content: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return _extract_text_pdf(content)
    elif name.endswith(".docx") or name.endswith(".doc"):
        return _extract_text_docx(content)
    return _extract_text_txt(content)


# ── Chunking ─────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = end - overlap
    return chunks


# ── Deterministic point IDs ───────────────────────────────────────────

def _point_id(company_id: int, reference_source_id: str, chunk_index: int) -> str:
    key = f"{company_id}::{reference_source_id}::{chunk_index}"
    return str(uuid.UUID(hashlib.md5(key.encode()).hexdigest()))


# ── Core Qdrant operations ────────────────────────────────────────────

def delete_source_vectors(reference_source_id: str, company_id: int) -> None:
    """Remove all Qdrant chunks for a single reference source."""
    client = _get_qdrant()
    if client is None:
        logger.warning("delete_source_vectors: Qdrant unavailable, skipping ref=%s", reference_source_id)
        return
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        client.delete(
            collection_name=REFERENCES_COLLECTION,
            points_selector=Filter(
                must=[
                    FieldCondition(key="company_id", match=MatchValue(value=int(company_id))),
                    FieldCondition(key="reference_source_id", match=MatchValue(value=str(reference_source_id))),
                ]
            ),
        )
        retrieve_reference_chunks.cache_clear()
        logger.info("Deleted Qdrant vectors: ref=%s company=%s", reference_source_id, company_id)
    except Exception as e:
        logger.warning("delete_source_vectors failed: %s", e)


def get_source_chunk_count(reference_source_id: str, company_id: int) -> int:
    client = _get_qdrant()
    if client is None:
        return 0
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        result = client.count(
            collection_name=REFERENCES_COLLECTION,
            count_filter=Filter(
                must=[
                    FieldCondition(key="company_id", match=MatchValue(value=int(company_id))),
                    FieldCondition(key="reference_source_id", match=MatchValue(value=str(reference_source_id))),
                ]
            ),
        )
        return result.count
    except Exception:
        return 0


# ── Sync ingestion workers ────────────────────────────────────────────

def process_file_ingest(
    reference_source_id: str,
    company_id: int,
    title: str,
    category: str,
    source_filename: str,
    content: bytes,
) -> int:
    """
    Parse → chunk → embed → upsert into decisio_references.
    Returns chunk count on success. Raises on failure.
    """
    text = extract_text(source_filename, content)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Document produced no text chunks.")

    client = _get_qdrant()
    embedder = _get_embedder()
    if client is None or embedder is None:
        raise RuntimeError("Qdrant or embedder unavailable.")

    from qdrant_client.models import PointStruct

    delete_source_vectors(reference_source_id, company_id)

    BATCH = 50
    points = []
    for batch_start in range(0, len(chunks), BATCH):
        batch = chunks[batch_start: batch_start + BATCH]
        try:
            vectors = embedder.encode_batch(batch)
        except AttributeError:
            vectors = [embedder.encode(c) for c in batch]

        for i, (chunk, vec) in enumerate(zip(batch, vectors)):
            idx = batch_start + i
            points.append(
                PointStruct(
                    id=_point_id(company_id, reference_source_id, idx),
                    vector=vec,
                    payload={
                        "company_id": int(company_id),
                        "reference_source_id": str(reference_source_id),
                        "memory_type": "reference",
                        "category": category,
                        "source_type": "file",
                        "source_filename": source_filename,
                        "title": title,
                        "chunk_index": idx,
                        "text": chunk,
                    },
                )
            )

    for batch_start in range(0, len(points), BATCH):
        client.upsert(collection_name=REFERENCES_COLLECTION, points=points[batch_start: batch_start + BATCH])

    retrieve_reference_chunks.cache_clear()
    logger.info("File ingested: ref=%s company=%s chunks=%d file=%s", reference_source_id, company_id, len(chunks), source_filename)
    return len(chunks)


def process_text_ingest(
    reference_source_id: str,
    company_id: int,
    title: str,
    category: str,
    problem: str,
    solution: str,
) -> int:
    """
    Build canonical text → chunk if long → embed → upsert into decisio_references.
    Returns chunk count.
    """
    canonical = f"Problem: {(problem or '').strip()}\nSolution: {(solution or '').strip()}"
    chunks = chunk_text(canonical)
    if not chunks:
        chunks = [canonical.strip() or " "]

    client = _get_qdrant()
    embedder = _get_embedder()
    if client is None or embedder is None:
        raise RuntimeError("Qdrant or embedder unavailable.")

    from qdrant_client.models import PointStruct

    delete_source_vectors(reference_source_id, company_id)

    try:
        vectors = embedder.encode_batch(chunks)
    except AttributeError:
        vectors = [embedder.encode(c) for c in chunks]

    points = [
        PointStruct(
            id=_point_id(company_id, reference_source_id, idx),
            vector=vec,
            payload={
                "company_id": int(company_id),
                "reference_source_id": str(reference_source_id),
                "memory_type": "reference",
                "category": category,
                "source_type": "text",
                "source_filename": "",
                "title": title,
                "chunk_index": idx,
                "text": chunk,
            },
        )
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]

    client.upsert(collection_name=REFERENCES_COLLECTION, points=points)
    retrieve_reference_chunks.cache_clear()
    logger.info("Text ingested: ref=%s company=%s chunks=%d", reference_source_id, company_id, len(chunks))
    return len(chunks)


# ── Retrieval ────────────────────────────────────────────────────────

EXCERPT_MAX_CHARS = 450  # safe excerpt length for trace / UI display


def resolve_source_ids(company_id: int, equipment_id: str | None) -> List[str]:
    """
    Return active reference_source UUIDs (as strings) for the given
    company + equipment context, using the scope rules:

      - company_wide: always included
      - equipment_specific: only if linked to this equipment_id
    """
    try:
        from src.db.session import SessionLocal
        from src.db.models import ReferenceSource, ReferenceEquipmentLink
        from sqlalchemy import select as _sel, or_ as _or, exists as _exists

        with SessionLocal() as session:
            eq_upper = (equipment_id or "").strip().upper()
            q = _sel(ReferenceSource.id).where(
                ReferenceSource.company_id == int(company_id),
                ReferenceSource.status == "active",
                _or(
                    ReferenceSource.scope == "company_wide",
                    _exists(
                        _sel(ReferenceEquipmentLink.id).where(
                            ReferenceEquipmentLink.reference_source_id == ReferenceSource.id,
                            ReferenceEquipmentLink.equipment_id == eq_upper,
                        ).correlate(ReferenceSource)
                    )
                    if eq_upper
                    else (ReferenceSource.scope == "equipment_specific"),  # no equipment → skip eq-specific
                ),
            )
            rows = session.execute(q).scalars().all()
            return [str(r) for r in rows]
    except Exception as e:
        logger.warning("resolve_source_ids failed: %s", e)
        return []


@lru_cache(maxsize=32)
def retrieve_reference_chunks(
    company_id: int,
    equipment_id: str,
    query_text: str,
    limit: int = 5,
) -> List[dict]:
    """
    Retrieve the most relevant reference chunks for the given company/equipment
    and query text.  Scope-aware: company-wide + equipment-specific active refs.

    Returns list of dicts: {text, chunk_index, source_filename, title, category, score}.
    """
    source_ids = resolve_source_ids(company_id, equipment_id)
    if not source_ids:
        return []

    client = _get_qdrant()
    embedder = _get_embedder()
    if client is None or embedder is None:
        return []

    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

        vec = embedder.encode(query_text)
        search_filter = Filter(
            must=[
                FieldCondition(key="company_id", match=MatchValue(value=int(company_id))),
                FieldCondition(key="reference_source_id", match=MatchAny(any=source_ids)),
                FieldCondition(key="memory_type", match=MatchValue(value="reference")),
            ]
        )

        results = []
        try:
            results = client.search(
                collection_name=REFERENCES_COLLECTION,
                query_vector=vec,
                query_filter=search_filter,
                limit=limit,
                with_payload=True,
            )
        except Exception:
            try:
                res = client.query_points(
                    collection_name=REFERENCES_COLLECTION,
                    query=vec,
                    query_filter=search_filter,
                    limit=limit,
                    with_payload=True,
                )
                results = list(res.points)
            except Exception as e2:
                logger.warning("retrieve_reference_chunks search failed: %s", e2)
                return []

        chunks = []
        for hit in results:
            payload = getattr(hit, "payload", None) or {}
            score = float(getattr(hit, "score", 0) or 0)
            if score < SCORE_THRESHOLD:
                continue
            chunks.append({
                "text": payload.get("text", ""),
                "chunk_index": payload.get("chunk_index", 0),
                "source_filename": payload.get("source_filename", ""),
                "title": payload.get("title", ""),
                "category": payload.get("category", ""),
                "score": round(score, 3),
            })
        return chunks

    except Exception as e:
        logger.warning("retrieve_reference_chunks failed: %s", e)
        return []


# ── Trace-aware retrieval ─────────────────────────────────────────────

def resolve_source_metadata(company_id: int, source_ids: List[str]) -> List[dict]:
    """
    Fetch scope + title + category for a list of reference_source UUIDs.
    Used to enrich trace hits with scope information that is not stored
    in each Qdrant chunk payload.

    Returns list of dicts: {id, title, category, scope, equipment_ids}.
    Equipment_ids is the list of linked equipment IDs (empty for company_wide).
    """
    if not source_ids:
        return []
    try:
        from src.db.session import SessionLocal
        from src.db.models import ReferenceSource, ReferenceEquipmentLink
        from sqlalchemy import select as _sel, or_ as _or
        from sqlalchemy.orm import selectinload

        with SessionLocal() as session:
            import uuid as _uuid
            uuids = []
            for sid in source_ids:
                try:
                    uuids.append(_uuid.UUID(sid))
                except ValueError:
                    pass
            rows = session.execute(
                _sel(ReferenceSource)
                .options(selectinload(ReferenceSource.equipment_links))
                .where(
                    ReferenceSource.company_id == int(company_id),
                    ReferenceSource.id.in_(uuids),
                )
            ).scalars().all()
            result = []
            for r in rows:
                eq_ids = [lnk.equipment_id for lnk in (r.equipment_links or [])]
                result.append({
                    "id": str(r.id),
                    "title": r.title,
                    "category": r.category,
                    "scope": r.scope,
                    "equipment_ids": eq_ids,
                })
            return result
    except Exception as e:
        logger.warning("resolve_source_metadata failed: %s", e)
        return []


def retrieve_with_trace(
    company_id: int,
    equipment_id: str,
    query_text: str,
    limit: int = 5,
) -> dict:
    """
    Scope-aware retrieval that returns both:
      - ``chunks``:  list of dicts suitable for injecting into LLM prompts
                     (text, chunk_index, source_filename, title, category, score)
      - ``trace``:   structured retrieval audit record:
                     {
                       "retrieval_query": str,
                       "asset_id": str,
                       "eligible_reference_source_ids": [str, ...],
                       "eligible_sources": [{id, title, category, scope, equipment_ids}],
                       "retrieved_hits": [
                         {
                           reference_source_id, title, category, source_type,
                           scope, equipment_ids, chunk_index, score, excerpt
                         }
                       ]
                     }

    Never exposes raw embeddings or full chunk text.
    Excerpts are capped at EXCERPT_MAX_CHARS characters.
    Scores are rounded to 3 decimal places.
    """
    eq_upper = (equipment_id or "").strip().upper()
    source_ids = resolve_source_ids(company_id, eq_upper)
    meta_by_id = {m["id"]: m for m in resolve_source_metadata(company_id, source_ids)}

    base_trace = {
        "retrieval_query": (query_text or "")[:500],
        "asset_id": eq_upper,
        "eligible_reference_source_ids": list(source_ids),
        "eligible_sources": list(meta_by_id.values()),
        "retrieved_hits": [],
    }

    if not source_ids:
        return {"chunks": [], "trace": base_trace}

    client = _get_qdrant()
    embedder = _get_embedder()
    if client is None or embedder is None:
        return {"chunks": [], "trace": base_trace}

    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue, MatchAny

        vec = embedder.encode(query_text)
        search_filter = Filter(
            must=[
                FieldCondition(key="company_id", match=MatchValue(value=int(company_id))),
                FieldCondition(key="reference_source_id", match=MatchAny(any=source_ids)),
                FieldCondition(key="memory_type", match=MatchValue(value="reference")),
            ]
        )

        raw_results = []
        try:
            raw_results = client.search(
                collection_name=REFERENCES_COLLECTION,
                query_vector=vec,
                query_filter=search_filter,
                limit=limit,
                with_payload=True,
            )
        except Exception:
            try:
                res = client.query_points(
                    collection_name=REFERENCES_COLLECTION,
                    query=vec,
                    query_filter=search_filter,
                    limit=limit,
                    with_payload=True,
                )
                raw_results = list(res.points)
            except Exception as e2:
                logger.warning("retrieve_with_trace search failed: %s", e2)
                return {"chunks": [], "trace": base_trace}

        chunks = []
        hits = []
        for hit in raw_results:
            payload = getattr(hit, "payload", None) or {}
            score = round(float(getattr(hit, "score", 0) or 0), 3)
            if score < SCORE_THRESHOLD:
                continue

            ref_id = payload.get("reference_source_id", "")
            chunk_text = payload.get("text", "")
            chunk_idx = payload.get("chunk_index", 0)
            title = payload.get("title", "")
            category = payload.get("category", "")
            source_type = payload.get("source_type", "")

            # Resolve scope and equipment_ids from metadata (not from Qdrant payload)
            meta = meta_by_id.get(ref_id, {})
            scope = meta.get("scope", "")
            eq_ids = meta.get("equipment_ids", [])

            chunks.append({
                "text": chunk_text,
                "chunk_index": chunk_idx,
                "source_filename": payload.get("source_filename", ""),
                "title": title,
                "category": category,
                "score": score,
            })

            excerpt = chunk_text[:EXCERPT_MAX_CHARS].strip()
            if len(chunk_text) > EXCERPT_MAX_CHARS:
                excerpt += "…"

            hits.append({
                "reference_source_id": ref_id,
                "title": title,
                "category": category,
                "source_type": source_type,
                "scope": scope,
                "equipment_ids": eq_ids,
                "chunk_index": chunk_idx,
                "score": score,
                "excerpt": excerpt,
            })

        trace = {**base_trace, "retrieved_hits": hits}
        return {"chunks": chunks, "trace": trace}

    except Exception as e:
        logger.warning("retrieve_with_trace failed: %s", e)
        return {"chunks": [], "trace": base_trace}


# ── Migration helper ──────────────────────────────────────────────────

def repoint_qdrant_payload(
    source_collection: str,
    reference_source_id: str,
    company_id: int,
    chunk_points: list[dict],
) -> int:
    """
    Copy existing vectors from source_collection into decisio_references,
    updating payload to include reference_source_id.  Vectors are NOT
    re-embedded — original float arrays are copied as-is.

    chunk_points: list of {id, vector, payload} dicts (from migration scroll).
    Returns number of points upserted.
    """
    client = _get_qdrant()
    if client is None:
        raise RuntimeError("Qdrant unavailable for migration repoint.")

    from qdrant_client.models import PointStruct

    BATCH = 50
    points = []
    for i, p in enumerate(chunk_points):
        new_payload = dict(p.get("payload", {}))
        new_payload["reference_source_id"] = str(reference_source_id)
        new_payload["memory_type"] = "reference"
        new_payload["company_id"] = int(company_id)
        points.append(
            PointStruct(
                id=_point_id(company_id, reference_source_id, i),
                vector=p["vector"],
                payload=new_payload,
            )
        )

    for batch_start in range(0, len(points), BATCH):
        client.upsert(collection_name=REFERENCES_COLLECTION, points=points[batch_start: batch_start + BATCH])

    retrieve_reference_chunks.cache_clear()
    return len(points)
