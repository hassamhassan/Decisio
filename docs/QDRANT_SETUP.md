# Qdrant setup (Decision Memory)

Decisio uses [Qdrant](https://qdrant.tech/) as the vector store for **Decision Memory**: embeddings of incident patterns and expert reasoning for retrieval during diagnosis.

## Quick start

1. **Start Qdrant** (Docker):
   ```bash
   docker compose up -d
   ```
   This runs Qdrant on `http://localhost:6333` with a persistent volume.

2. **Configure the app**  
   In `.env` (copy from `.env.example` if needed):
   ```env
   QDRANT_URL=http://localhost:6333
   ```

3. **Seed Decision Memory** (optional but recommended):
   ```bash
   python -m src.data.seed_memory
   ```
   This creates the `decisio_patterns` collection and loads sample incident patterns.

4. **Run the app**  
   The Retrieval Agent and Memory Write Agent will use Qdrant when `QDRANT_URL` is set.

## Behaviour

- **`QDRANT_URL` set** → App connects to the Qdrant server (e.g. Docker). Persisted data.
- **`QDRANT_URL` unset** → In-memory Qdrant is used (no persistence; useful for tests or one-off runs).

## Collection

- **Name:** `decisio_patterns`
- **Embedding model:** `BAAI/bge-base-en-v1.5` (sentence-transformers; strong MTEB performance)
- **Vector size:** 768
- **Distance:** Cosine

If you had an existing collection created with the previous 384-d model, delete the `decisio_patterns` collection in Qdrant (or run a fresh Qdrant) and re-run `python -m src.data.seed_memory`.

## API

- REST: http://localhost:6333  
- Dashboard: http://localhost:6333/dashboard  
- gRPC: port 6334 (optional)
