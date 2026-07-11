# ── Frontend build: compile the React/Vite dashboard to static assets ──
FROM node:20-alpine AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ── API image ──
FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python deps
COPY pyproject.toml .
RUN uv pip install --system --no-cache .

# Copy app + migrations
COPY api/ api/
COPY alembic/ alembic/
COPY alembic.ini .

# Bake the built dashboard (served by api.app.main:_mount_spa at web_dist_dir).
COPY --from=frontend /web/dist ./web/dist

# Create data directory
RUN mkdir -p data

EXPOSE 8200

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8200/health || exit 1

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8200"]
