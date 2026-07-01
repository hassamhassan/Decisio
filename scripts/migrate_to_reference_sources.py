"""
Decisio — Migration: knowledge_entries + decisio_manuals → reference_sources

Strategy (no concatenate / no re-embed):

  knowledge_entries (PG)
      → INSERT reference_sources (source_type=text, category=knowledge)
      → decisio_knowledge (Qdrant)
          existing vector found?  → copy point into decisio_references with updated payload
          no vector?              → schedule_text_ingest (re-embed from PG text)

  decisio_manuals (Qdrant)  — per (company_id, equipment_id)
      → INSERT reference_sources (source_type=file, category=manual, scope=equipment_specific)
      → scroll chunks from decisio_manuals
      → copy vectors into decisio_references with updated payload  (no re-embed)

Idempotent: skips rows where legacy_knowledge_id / legacy_manual_key already exists.

Usage:
    python -m scripts.migrate_to_reference_sources
    # or with specific company:
    python -m scripts.migrate_to_reference_sources --company-id 1
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import uuid
from pathlib import Path

# Add project root to sys.path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("migrate_reference_sources")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


# ── DB setup ─────────────────────────────────────────────────────────

def _get_session():
    from src.db.session import SessionLocal
    return SessionLocal()


def _compute_text_hash(problem: str, solution: str) -> str:
    canonical = f"Problem:{(problem or '').strip()}\nSolution:{(solution or '').strip()}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Qdrant helpers ────────────────────────────────────────────────────

def _get_qdrant():
    import os
    from qdrant_client import QdrantClient
    url = os.getenv("QDRANT_URL", "").strip()
    return QdrantClient(url=url) if url else QdrantClient(":memory:")


def _scroll_all(client, collection: str, scroll_filter) -> list[dict]:
    """Scroll all matching points from a Qdrant collection."""
    try:
        collections = [c.name for c in client.get_collections().collections]
        if collection not in collections:
            return []
    except Exception:
        return []

    results = []
    offset = None
    while True:
        try:
            batch, next_offset = client.scroll(
                collection_name=collection,
                scroll_filter=scroll_filter,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
        except Exception as e:
            logger.warning("Scroll failed on %s: %s", collection, e)
            break

        for point in batch:
            results.append({
                "id": point.id,
                "vector": list(getattr(point, "vector", None) or []),
                "payload": getattr(point, "payload", None) or {},
            })

        if next_offset is None:
            break
        offset = next_offset

    return results


def _upsert_into_references(client, company_id: int, reference_source_id: str,
                             points: list[dict], title: str, category: str,
                             source_type: str, source_filename: str = "") -> int:
    """Copy existing vectors into decisio_references with updated payload."""
    from qdrant_client.models import PointStruct

    REFERENCES_COLLECTION = "decisio_references"
    _ensure_collection(client, REFERENCES_COLLECTION)

    new_points = []
    for i, p in enumerate(points):
        vec = p.get("vector")
        if not vec:
            logger.warning("  Skipping point %s — no vector data.", p.get("id"))
            continue

        old_payload = dict(p.get("payload", {}))
        old_chunk_index = old_payload.get("chunk_index", i)

        key = f"{company_id}::{reference_source_id}::{old_chunk_index}"
        new_id = str(uuid.UUID(hashlib.md5(key.encode()).hexdigest()))

        new_payload = {
            "company_id": int(company_id),
            "reference_source_id": str(reference_source_id),
            "memory_type": "reference",
            "category": category,
            "source_type": source_type,
            "source_filename": old_payload.get("source_filename", source_filename),
            "title": title,
            "chunk_index": old_chunk_index,
            "text": old_payload.get("text", ""),
        }

        new_points.append(PointStruct(id=new_id, vector=vec, payload=new_payload))

    BATCH = 50
    for start in range(0, len(new_points), BATCH):
        client.upsert(
            collection_name=REFERENCES_COLLECTION,
            points=new_points[start: start + BATCH],
        )

    return len(new_points)


def _ensure_collection(client, name: str):
    from qdrant_client.models import Distance, VectorParams, PayloadSchemaType
    import os

    collections = [c.name for c in client.get_collections().collections]
    if name not in collections:
        dim = int(os.getenv("DECISIO_EMBEDDING_DIMENSION", "1536"))
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        for field, schema in [
            ("company_id", PayloadSchemaType.INTEGER),
            ("reference_source_id", PayloadSchemaType.KEYWORD),
            ("memory_type", PayloadSchemaType.KEYWORD),
        ]:
            try:
                client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=schema,
                )
            except Exception:
                pass


# ── knowledge_entries migration ───────────────────────────────────────

def migrate_knowledge_entries(session, client, company_id: int | None = None):
    from sqlalchemy import select as sel
    from src.db.models import KnowledgeEntry, ReferenceSource, ReferenceEquipmentLink
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    q = sel(KnowledgeEntry)
    if company_id is not None:
        q = q.where(KnowledgeEntry.company_id == company_id)

    rows = session.execute(q).scalars().all()
    logger.info("knowledge_entries to migrate: %d", len(rows))

    for entry in rows:
        # Idempotency check
        existing = session.execute(
            sel(ReferenceSource).where(
                ReferenceSource.legacy_knowledge_id == entry.id
            )
        ).scalar_one_or_none()
        if existing:
            logger.debug("  Skip already-migrated KB entry %s", entry.id)
            continue

        scope = "equipment_specific" if entry.equipment_id else "company_wide"
        title = f"KB: {(entry.problem or '')[:80]}"
        content_hash = _compute_text_hash(entry.problem or "", entry.solution or "")

        ref_id = uuid.uuid4()
        ref = ReferenceSource(
            id=ref_id,
            company_id=entry.company_id,
            title=title,
            source_type="text",
            category="knowledge",
            scope=scope,
            problem=entry.problem,
            solution=entry.solution,
            tags=entry.tags or [],
            content_hash=content_hash,
            status="processing",
            chunk_count=0,
            legacy_knowledge_id=entry.id,
            created_by=entry.created_by,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )
        session.add(ref)
        session.flush()

        if entry.equipment_id:
            session.add(ReferenceEquipmentLink(
                reference_source_id=ref_id,
                equipment_id=entry.equipment_id.upper(),
                company_id=entry.company_id,
            ))
            session.flush()

        # Try to repoint existing Qdrant vector
        qdrant_points = []
        if entry.vector_id:
            try:
                result = client.retrieve(
                    collection_name="decisio_knowledge",
                    ids=[entry.vector_id],
                    with_vectors=True,
                    with_payload=True,
                )
                if result:
                    p = result[0]
                    qdrant_points = [{
                        "id": p.id,
                        "vector": list(getattr(p, "vector", None) or []),
                        "payload": getattr(p, "payload", None) or {},
                    }]
            except Exception as e:
                logger.debug("  Could not retrieve knowledge vector %s: %s", entry.vector_id, e)

        if qdrant_points and qdrant_points[0].get("vector"):
            chunk_count = _upsert_into_references(
                client,
                company_id=entry.company_id,
                reference_source_id=str(ref_id),
                points=qdrant_points,
                title=title,
                category="knowledge",
                source_type="text",
            )
            ref.status = "active"
            ref.chunk_count = chunk_count
            session.flush()
            logger.info("  KB %s → ref %s (repointed %d vector)", entry.id, ref_id, chunk_count)
        else:
            # Re-embed from PG text
            try:
                from src.services.reference_service import process_text_ingest
                chunk_count = process_text_ingest(
                    reference_source_id=str(ref_id),
                    company_id=entry.company_id,
                    title=title,
                    category="knowledge",
                    problem=entry.problem or "",
                    solution=entry.solution or "",
                )
                ref.status = "active"
                ref.chunk_count = chunk_count
                session.flush()
                logger.info("  KB %s → ref %s (re-embedded %d chunks)", entry.id, ref_id, chunk_count)
            except Exception as e:
                ref.status = "failed"
                ref.processing_error = str(e)[:2000]
                session.flush()
                logger.warning("  KB %s embed failed: %s", entry.id, e)

        session.commit()

    logger.info("knowledge_entries migration complete.")


# ── decisio_manuals migration ─────────────────────────────────────────

def migrate_manuals(session, client, company_id: int | None = None):
    from sqlalchemy import select as sel
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    from src.db.models import ReferenceSource, ReferenceEquipmentLink, Equipment

    # Find all (company_id, equipment_id) combinations in decisio_manuals
    try:
        collections = [c.name for c in client.get_collections().collections]
        if "decisio_manuals" not in collections:
            logger.info("decisio_manuals collection not found — nothing to migrate.")
            return
    except Exception as e:
        logger.warning("Could not check collections: %s", e)
        return

    # Scroll to discover all unique (company_id, equipment_id) combinations
    pairs: set[tuple[int, str]] = set()
    offset = None
    while True:
        f = None
        if company_id is not None:
            f = Filter(must=[FieldCondition(key="company_id", match=MatchValue(value=int(company_id)))])
        try:
            batch, next_offset = client.scroll(
                collection_name="decisio_manuals",
                scroll_filter=f,
                limit=200,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as e:
            logger.warning("Could not scroll decisio_manuals: %s", e)
            break

        for point in batch:
            payload = getattr(point, "payload", None) or {}
            cid = payload.get("company_id")
            eid = payload.get("equipment_id")
            if cid and eid:
                pairs.add((int(cid), str(eid).upper()))

        if next_offset is None:
            break
        offset = next_offset

    logger.info("Manual (company_id, equipment_id) pairs found: %d", len(pairs))

    for (cid, eid) in pairs:
        legacy_key = f"{cid}:{eid}"

        # Idempotency
        existing = session.execute(
            sel(ReferenceSource).where(
                ReferenceSource.legacy_manual_key == legacy_key
            )
        ).scalar_one_or_none()
        if existing:
            logger.debug("  Skip already-migrated manual %s", legacy_key)
            continue

        # Look up equipment name
        eq_row = session.execute(
            sel(Equipment).where(
                Equipment.id == eid,
                Equipment.company_id == cid,
            )
        ).scalar_one_or_none()
        equipment_name = eq_row.name if eq_row else eid

        # Scroll all chunks for this manual
        scroll_filter = Filter(
            must=[
                FieldCondition(key="company_id", match=MatchValue(value=cid)),
                FieldCondition(key="equipment_id", match=MatchValue(value=eid)),
                FieldCondition(key="memory_type", match=MatchValue(value="manual")),
            ]
        )
        points = _scroll_all(client, "decisio_manuals", scroll_filter)
        if not points:
            logger.warning("  No chunks for manual %s — skipping.", legacy_key)
            continue

        source_filename = points[0].get("payload", {}).get("source_filename", f"{eid}_manual")
        title = f"Manual: {equipment_name}"

        ref_id = uuid.uuid4()
        ref = ReferenceSource(
            id=ref_id,
            company_id=cid,
            title=title,
            source_type="file",
            category="manual",
            scope="equipment_specific",
            source_filename=source_filename,
            status="processing",
            chunk_count=0,
            legacy_manual_key=legacy_key,
        )
        session.add(ref)
        session.flush()

        session.add(ReferenceEquipmentLink(
            reference_source_id=ref_id,
            equipment_id=eid,
            company_id=cid,
        ))
        session.flush()

        try:
            chunk_count = _upsert_into_references(
                client,
                company_id=cid,
                reference_source_id=str(ref_id),
                points=points,
                title=title,
                category="manual",
                source_type="file",
                source_filename=source_filename,
            )
            ref.status = "active"
            ref.chunk_count = chunk_count
            session.flush()
            logger.info("  Manual %s → ref %s (%d chunks repointed)", legacy_key, ref_id, chunk_count)
        except Exception as e:
            ref.status = "failed"
            ref.processing_error = str(e)[:2000]
            session.flush()
            logger.warning("  Manual %s repoint failed: %s", legacy_key, e)

        session.commit()

    logger.info("decisio_manuals migration complete.")


# ── Entry point ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Migrate KB + manuals to reference_sources.")
    parser.add_argument("--company-id", type=int, default=None, help="Migrate a single company only.")
    parser.add_argument("--skip-manuals", action="store_true", help="Skip Qdrant manual migration.")
    parser.add_argument("--skip-knowledge", action="store_true", help="Skip knowledge_entries migration.")
    args = parser.parse_args()

    session = _get_session()
    client = _get_qdrant()

    try:
        if not args.skip_knowledge:
            logger.info("=== Migrating knowledge_entries ===")
            migrate_knowledge_entries(session, client, company_id=args.company_id)

        if not args.skip_manuals:
            logger.info("=== Migrating decisio_manuals ===")
            migrate_manuals(session, client, company_id=args.company_id)

        logger.info("Migration completed successfully.")
    except Exception as e:
        logger.error("Migration failed: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
