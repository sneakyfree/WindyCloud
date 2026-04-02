FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy app
COPY api/ api/

# Create data directory
RUN mkdir -p data

EXPOSE 8200

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8200/health || exit 1

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8200"]
