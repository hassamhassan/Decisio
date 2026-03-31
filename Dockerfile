# Decisio — multi-stage: build frontend, then run backend + serve frontend
# Run: docker compose up -d (postgres + qdrant + api)

# ── Stage 1: Frontend build (Debian base so Rollup optional deps resolve for linux/gnu) ──
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json* ./
# Fresh install in-container so optional deps (e.g. @rollup/rollup-linux-x64-gnu) match this OS
RUN rm -rf node_modules && npm ci 2>/dev/null || npm install

COPY frontend/ ./
RUN npm run build

# ── Stage 2: Backend + serve frontend ─────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# System deps (kept minimal for faster CI)
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_DEFAULT_TIMEOUT=600
ENV HF_HUB_DISABLE_TELEMETRY=1
RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Backend code
COPY api.py ./
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY src/ ./src/
COPY conftest.py* ./

# Frontend static (from stage 1)
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Non-root user
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
# DATABASE_URL, GROQ_API_KEY, QDRANT_URL, JWT_SECRET_KEY set via docker-compose / env

# Run migrations then start API
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn api:app --host 0.0.0.0 --port 8000"]
