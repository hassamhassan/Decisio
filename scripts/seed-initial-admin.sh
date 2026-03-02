#!/usr/bin/env bash
# Create the first super_admin user (bootstrap). Run once after docker compose up.
# Usage: ./scripts/seed-initial-admin.sh [username] [password]
# Default: admin / admin (change in production)

set -e
API_URL="${API_URL:-http://localhost:8000}"
USERNAME="${1:-admin}"
PASSWORD="${2:-admin}"

echo "Creating first user (super_admin): $USERNAME at $API_URL"
resp=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/api/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"username\": \"$USERNAME\", \"email\": \"$USERNAME@localhost\", \"password\": \"$PASSWORD\", \"full_name\": \"Super Admin\"}")

body=$(echo "$resp" | head -n -1)
code=$(echo "$resp" | tail -n 1)

if [ "$code" = "200" ]; then
  echo "Success. You can log in at $API_URL with $USERNAME / $PASSWORD"
  echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body"
else
  echo "Failed (HTTP $code): $body"
  exit 1
fi
