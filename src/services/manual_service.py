"""
Decisio — Machine Manual Ingestion Service

Handles parsing, chunking, embedding, and Qdrant storage
of uploaded machine manuals (PDF, DOCX, TXT).

Manuals are stored in the `decisio_manuals` Qdrant collection,
separate from `decisio_patterns` (decision memory).

Metadata per chunk:
    {
        "company_id": int,
        "equipment_id": str,
        "equipment_name": str,
        "memory_type": "manual",
        "chunk_index": int,
        "source_filename": str,
        "text": str,  (stored for retrieval display)
    }
"""

from __future__ import annotations

import os
import io
import logging
import hashlib
import uuid
from typing import List
from functools import lru_cache

logger = logging.getLogger(__name__)

# ── Collection name ───────────────────────────────────────────────────
MANUALS_COLLECTION = "decisio_manuals"

# ── Chunking config ──────────────────────────────────────────────────
CHUNK_SIZE = 800        # approximate chars per chunk (not tokens, for simplicity)
CHUNK_OVERLAP = 200     # overlap between adjacent chunks


# ── Lazy singletons (shared with retrieval_agent) ─────────────────────

_qdrant_client = None
_embedder = None


def _get_qdrant():
    """Lazy-init Qdrant client."""
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

        # Ensure the manuals collection exists
        collections = [c.name for c in _qdrant_client.get_collections().collections]
        if MANUALS_COLLECTION not in collections:
            dim = _get_embedding_dimension()
            _qdrant_client.create_collection(
                collection_name=MANUALS_COLLECTION,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
            )
            # Payload indices for fast filtering
            for field, schema in [
                ("company_id", PayloadSchemaType.INTEGER),
                ("equipment_id", PayloadSchemaType.KEYWORD),
                ("memory_type", PayloadSchemaType.KEYWORD),
            ]:
                try:
                    _qdrant_client.create_payload_index(
                        collection_name=MANUALS_COLLECTION,
                        field_name=field,
                        field_schema=schema,
                    )
                except Exception:
                    pass

        return _qdrant_client
    except Exception as e:
        logger.warning("Qdrant not available for manuals: %s", e)
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

            def encode_batch(self, texts: list[str]) -> list[list]:
                cleaned = [(t or "").strip() or " " for t in texts]
                cleaned = [t[:32_000] for t in cleaned]
                return self._client.embed_documents(cleaned)

        _embedder = _Adapter(key=api_key)
        return _embedder
    except Exception as e:
        logger.warning("Embedder unavailable for manuals: %s", e)
        return None


def _get_embedding_dimension() -> int:
    raw = os.getenv("DECISIO_EMBEDDING_DIMENSION", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return 1536  # default for text-embedding-3-small


# ── Text extraction ───────────────────────────────────────────────────

def _extract_text_txt(content: bytes) -> str:
    try:
        return content.decode("utf-8", errors="replace")
    except Exception:
        return content.decode("latin-1", errors="replace")


def _extract_text_pdf(content: bytes) -> str:
    """Extract text from PDF, trying pypdf (plain then layout) then pdfminer.six."""
    text = ""

    # ── Attempt 1: pypdf plain mode ───────────────────────────────────
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                pass
        text = "\n".join(pages).strip()
    except Exception:
        pass

    # ── Attempt 2: pypdf layout mode ─────────────────────────────────
    if not text:
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text(extraction_mode="layout") or "")
                except Exception:
                    pass
            text = "\n".join(pages).strip()
        except Exception:
            pass

    # ── Attempt 3: pdfminer.six (handles complex encodings better) ───
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
    """Dispatch to the correct parser based on file extension."""
    name = filename.lower()
    if name.endswith(".pdf"):
        return _extract_text_pdf(content)
    elif name.endswith(".docx") or name.endswith(".doc"):
        return _extract_text_docx(content)
    else:
        return _extract_text_txt(content)


# ── Chunking ──────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Split text into overlapping chunks."""
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


# ── Stable point ID ───────────────────────────────────────────────────

def _point_id(company_id: int, equipment_id: str, chunk_index: int) -> str:
    """Deterministic UUID from the chunk key so we can overwrite on re-upload."""
    key = f"{company_id}::{equipment_id.upper()}::{chunk_index}"
    return str(uuid.UUID(hashlib.md5(key.encode()).hexdigest()))


# ── Public API ────────────────────────────────────────────────────────

def ingest_manual(
    company_id: int,
    equipment_id: str,
    equipment_name: str,
    filename: str,
    content: bytes,
) -> int:
    """
    Parse, chunk, embed, and store a machine manual in Qdrant.

    Returns the number of chunks stored.
    Raises ValueError on unsupported file type or parse error.
    """
    equipment_id = equipment_id.upper()

    # 1. Extract text (raises ValueError if no text found)
    text = extract_text(filename, content)

    # 2. Chunk
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("Document produced no text chunks.")

    client = _get_qdrant()
    embedder = _get_embedder()

    if client is None or embedder is None:
        raise RuntimeError("Qdrant or embedder is not available.")

    from qdrant_client.models import PointStruct

    # 3. Delete previous vectors for this equipment (full manual replacement)
    delete_manual(company_id, equipment_id)
    retrieve_manual_chunks.cache_clear()

    # 4. Embed and upsert in batches
    BATCH_SIZE = 50
    points = []
    
    # Process embeddings in batches
    for batch_start in range(0, len(chunks), BATCH_SIZE):
        batch_chunks = chunks[batch_start:batch_start + BATCH_SIZE]
        try:
            vectors = embedder.encode_batch(batch_chunks)
        except AttributeError:
            # Fallback if encode_batch isn't present
            vectors = [embedder.encode(c) for c in batch_chunks]
            
        for i, (chunk, vec) in enumerate(zip(batch_chunks, vectors)):
            global_idx = batch_start + i
            point_id = _point_id(company_id, equipment_id, global_idx)
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vec,
                    payload={
                        "company_id": int(company_id),
                        "equipment_id": equipment_id,
                        "equipment_name": equipment_name,
                        "memory_type": "manual",
                        "chunk_index": global_idx,
                        "source_filename": filename,
                        "text": chunk,
                    },
                )
            )

    for batch_start in range(0, len(points), BATCH_SIZE):
        batch = points[batch_start: batch_start + BATCH_SIZE]
        client.upsert(collection_name=MANUALS_COLLECTION, points=batch)

    logger.info(
        "Manual ingested: equipment=%s company=%s chunks=%d file=%s",
        equipment_id, company_id, len(chunks), filename,
    )
    return len(chunks)


def delete_manual(company_id: int, equipment_id: str) -> None:
    """Remove all manual chunks for a specific piece of equipment from Qdrant."""
    equipment_id = equipment_id.upper()
    client = _get_qdrant()
    if client is None:
        logger.warning("delete_manual: Qdrant client unavailable, skipping deletion for equipment=%s", equipment_id)
        return
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    client.delete(
        collection_name=MANUALS_COLLECTION,
        points_selector=Filter(
            must=[
                FieldCondition(key="company_id", match=MatchValue(value=int(company_id))),
                FieldCondition(key="equipment_id", match=MatchValue(value=equipment_id)),
            ]
        ),
    )
    logger.info("Manual deleted from Qdrant: equipment=%s company=%s", equipment_id, company_id)
    retrieve_manual_chunks.cache_clear()


def get_manual_chunk_count(company_id: int, equipment_id: str) -> int:
    """Return how many chunks are stored for a given equipment's manual."""
    equipment_id = equipment_id.upper()
    client = _get_qdrant()
    if client is None:
        return 0
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        result = client.count(
            collection_name=MANUALS_COLLECTION,
            count_filter=Filter(
                must=[
                    FieldCondition(key="company_id", match=MatchValue(value=int(company_id))),
                    FieldCondition(key="equipment_id", match=MatchValue(value=equipment_id)),
                ]
            ),
        )
        return result.count
    except Exception:
        return 0


@lru_cache(maxsize=32)
def retrieve_manual_chunks(
    equipment_id: str,
    query_text: str,
    company_id: int,
    limit: int = 5,
) -> List[dict]:
    """
    Retrieve the most relevant manual chunks for the given equipment and query.
    Returns a list of dicts with keys: text, chunk_index, source_filename, score.
    """
    equipment_id = equipment_id.upper()
    client = _get_qdrant()
    embedder = _get_embedder()
    if client is None or embedder is None:
        return []

    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        vec = embedder.encode(query_text)
        search_filter = Filter(
            must=[
                FieldCondition(key="company_id", match=MatchValue(value=int(company_id))),
                FieldCondition(key="equipment_id", match=MatchValue(value=equipment_id)),
                FieldCondition(key="memory_type", match=MatchValue(value="manual")),
            ]
        )

        results = []
        # Try older .search() API first, then newer query_points
        try:
            results = client.search(
                collection_name=MANUALS_COLLECTION,
                query_vector=vec,
                query_filter=search_filter,
                limit=limit,
                with_payload=True,
            )
        except Exception:
            try:
                res = client.query_points(
                    collection_name=MANUALS_COLLECTION,
                    query=vec,
                    query_filter=search_filter,
                    limit=limit,
                    with_payload=True,
                )
                results = list(res.points)
            except Exception as e2:
                logger.warning("Manual retrieval failed: %s", e2)
                return []

        chunks = []
        for hit in results:
            payload = getattr(hit, "payload", None) or {}
            score = float(getattr(hit, "score", 0) or 0)
            if score < 0.3:
                continue
            chunks.append({
                "text": payload.get("text", ""),
                "chunk_index": payload.get("chunk_index", 0),
                "source_filename": payload.get("source_filename", ""),
                "score": round(score, 3),
            })
        return chunks

    except Exception as e:
        logger.warning("retrieve_manual_chunks failed: %s", e)
        return []
