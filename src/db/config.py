"""
Decisio — Database Configuration

Reads DATABASE_URL from environment.
Supports both sync (Alembic migrations) and async (API runtime) engines.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# Default: local PostgreSQL via peer auth
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/decisio",
)

# Async variant for the FastAPI runtime
ASYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql://", "postgresql+asyncpg://", 1
)

# Sync variant for Alembic migrations
SYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql+asyncpg://", "postgresql://", 1
)
