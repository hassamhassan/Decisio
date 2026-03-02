# Deploy Decisio Without Vector Store

This guide walks through deploying Decisio **without Qdrant** (no vector store / no embedding model). The retrieval agent is disabled; diagnosis and decision briefs use LLM-only reasoning.

---

## Prerequisites

- **Docker** and **Docker Compose** installed
- **GROQ API key** for the LLM ([groq.com](https://console.groq.com))
- (Optional) A strong **JWT secret** for production

---

## Step 1: Clone and enter the project

```bash
cd /path/to/Decisio
```

---

## Step 2: Create environment file

Create a `.env` file in the project root (or copy from `.env.example`):

```bash
cp .env.example .env
```

Edit `.env` and set at least:

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | **Yes** | Your Groq API key for the LLM |
| `GROQ_MODEL` | No | Default: `llama-3.3-70b-versatile` |
| `JWT_SECRET_KEY` | **Yes in production** | Strong random secret; default is for dev only |
| `WS_BASE_URL` | No | Base URL for WebSocket (e.g. `https://your-domain.com`) |

**Example `.env` (minimal):**

```env
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=llama-3.3-70b-versatile
JWT_SECRET_KEY=change-me-in-production
```

Do **not** set `QDRANT_URL`; the app will not use Qdrant when the retrieval agent is disabled.

---

## Step 3: Start the stack (no Qdrant)

Use the no-vectorstore Compose file so only Postgres and the API run:

```bash
docker compose -f docker-compose.no-vectorstore.yml up -d --build
```

- **Postgres** will start and run health checks.
- **API** will start after Postgres is healthy, run Alembic migrations, then listen on port 8000.

Check that both containers are up:

```bash
docker compose -f docker-compose.no-vectorstore.yml ps
```

---

## Step 4: Run database migrations

Migrations run automatically when the API container starts (`alembic upgrade head` in the Dockerfile). If you need to run them manually (e.g. after a failed first start):

```bash
docker compose -f docker-compose.no-vectorstore.yml run --rm api alembic upgrade head
```

---

## Step 5: Create the first user (super admin)

From the project root:

```bash
./scripts/seed-initial-admin.sh
```

Default credentials: **admin** / **admin**. To use a different username and password:

```bash
./scripts/seed-initial-admin.sh myadmin mySecurePassword
```

If the API is not on `http://localhost:8000`, set `API_URL`:

```bash
API_URL=http://your-server:8000 ./scripts/seed-initial-admin.sh
```

---

## Step 6: Open the app

- **URL:** http://localhost:8000 (or your server host/port)
- **Login:** Use the credentials from Step 5.

You can create incidents, answer diagnostic questions, get decision briefs, and use escalation. Similar-past-incidents (Decision Memory) will be empty because the vector store is not used.

---

## Optional: Reset the database

To wipe Postgres and start over (e.g. new dev environment), use the no-vectorstore compose file:

```bash
docker compose -f docker-compose.no-vectorstore.yml down
docker volume rm decisio_postgres_data 2>/dev/null || true
docker compose -f docker-compose.no-vectorstore.yml up -d
./scripts/seed-initial-admin.sh
```

---

## Production checklist (no vector store)

1. **Set a strong `JWT_SECRET_KEY`** in `.env` (e.g. 32+ random bytes).
2. **Restrict CORS** in `api.py` if you host the frontend on another domain (replace `allow_origins=["*"]` with your frontend origin).
3. **Use HTTPS** in front of the API (reverse proxy: nginx, Caddy, or cloud load balancer).
4. **Set `WS_BASE_URL`** to your public URL with `https://` so the WebSocket escalation chat uses `wss://`.
5. **Back up Postgres** regularly (incidents, users, rules are stored there).
6. **Do not commit `.env`**; add `.env` to `.gitignore` if needed.

---

## Troubleshooting

| Issue | What to do |
|-------|------------|
| API exits with DB error | Ensure Postgres is healthy: `docker compose -f docker-compose.no-vectorstore.yml logs postgres`. Check `DATABASE_URL` matches Postgres user/password/db. |
| 401 on login | Create first user with `./scripts/seed-initial-admin.sh`. |
| LLM not answering / timeouts | Set `GROQ_API_KEY` in `.env` and restart API. Check Groq status and rate limits. |
| “Qdrant/embedder not available” in logs | Expected when running without vector store; retrieval is disabled and the app uses LLM-only reasoning. |

---

## Summary

| Step | Command / action |
|------|-------------------|
| 1 | `cd` to project |
| 2 | Copy `.env.example` to `.env`, set `GROQ_API_KEY` (and `JWT_SECRET_KEY` for prod) |
| 3 | `docker compose -f docker-compose.no-vectorstore.yml up -d --build` |
| 4 | Migrations run automatically on API start |
| 5 | `./scripts/seed-initial-admin.sh` |
| 6 | Open http://localhost:8000 and log in |

No Qdrant container or embedding model is required for this deployment.
