#!/usr/bin/env bash
# Run Alembic database migrations
set -euo pipefail

echo "=== Windy Cloud — Database Migration ==="

cd /app 2>/dev/null || cd "$(dirname "$0")/../.."

# Use DATABASE_URL from environment if set
if [ -n "${DATABASE_URL:-}" ]; then
    export ALEMBIC_DATABASE_URL="$DATABASE_URL"
    echo "Using DATABASE_URL from environment"
else
    echo "Using default SQLite (dev mode)"
fi

python -m alembic upgrade head
echo "Migration complete."
