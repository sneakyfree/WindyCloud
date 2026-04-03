#!/usr/bin/env bash
# Start Windy Cloud dev server — works from a fresh clone
set -euo pipefail

cd "$(dirname "$0")/.."

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    if command -v uv &> /dev/null; then
        uv venv .venv
    else
        python3 -m venv .venv
    fi
fi

source .venv/bin/activate

# Install/update dependencies
echo "Installing dependencies..."
if command -v uv &> /dev/null; then
    uv pip install -e ".[dev]"
else
    pip install -e ".[dev]"
fi

# Copy .env.example to .env if .env doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# Create data directory
mkdir -p data

echo ""
echo "Starting Windy Cloud on http://localhost:8200"
echo "  Storage: local_disk (set R2 credentials for cloud storage)"
echo "  Database: SQLite at data/windy_cloud.db"
echo "  API docs: http://localhost:8200/docs"
echo "  Portal:   http://localhost:8200/"
echo ""

uvicorn api.app.main:app --reload --port 8200
