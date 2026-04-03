#!/usr/bin/env bash
# Start Windy Cloud dev server
set -euo pipefail

cd "$(dirname "$0")/.."

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    uv venv .venv
fi

# Install/update dependencies
echo "Installing dependencies..."
source .venv/bin/activate
uv pip install -e ".[dev]"

# Create data directory
mkdir -p data

echo ""
echo "Starting Windy Cloud on http://localhost:8200"
echo "  Storage: local_disk (set R2 credentials for cloud storage)"
echo "  Database: SQLite at data/windy_cloud.db"
echo "  Docs: http://localhost:8200/docs"
echo ""

uvicorn api.app.main:app --reload --port 8200
