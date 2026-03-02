#!/usr/bin/env bash
# Stop stack, remove Postgres container + volume + image, then start fresh.
# Run from project root: ./scripts/postgres-reset.sh

set -e
cd "$(dirname "$0")/.."

echo "Stopping containers..."
docker compose down

echo "Removing Postgres volume (all DB data will be lost)..."
# Volume name is typically <project>_postgres_data (project = directory name)
vol="decisio_postgres_data"
docker volume rm "$vol" 2>/dev/null || docker volume rm "Decisio_postgres_data" 2>/dev/null || true

echo "Removing Postgres image..."
docker rmi postgres:16-alpine 2>/dev/null || true

echo "Starting fresh (will pull postgres image and create new volume)..."
docker compose up -d

echo "Done. Postgres is fresh. Run ./scripts/seed-initial-admin.sh to create first user."
