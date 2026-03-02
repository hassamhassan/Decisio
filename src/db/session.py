"""
Decisio — Database Session

Provides both async (FastAPI) and sync (LangGraph agents) SQLAlchemy
engine and session factories.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from src.db.config import ASYNC_DATABASE_URL, SYNC_DATABASE_URL

# ── Async engine (FastAPI runtime) ──────────────────────────────────

engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def get_session():
    """Yield an async session, auto-commit on success, rollback on error."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Sync engine (LangGraph agents) ─────────────────────────────────

sync_engine = create_engine(
    SYNC_DATABASE_URL,
    echo=False,
    pool_size=3,
    max_overflow=5,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=sync_engine,
    expire_on_commit=False,
)


# ── Lifecycle helpers ───────────────────────────────────────────────

async def init_db():
    """Create all tables (for development). In production, use Alembic."""
    from src.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Dispose both engine connection pools."""
    await engine.dispose()
    sync_engine.dispose()
