#!/usr/bin/env bash
# Windy Cloud — First Deployment Setup
# Usage: sudo ./deploy/setup.sh
set -euo pipefail

DOMAIN="${1:-cloud.windyfly.ai}"
PROJECT_DIR="${2:-/opt/windy-cloud}"

echo "╔══════════════════════════════════════╗"
echo "║     Windy Cloud — Deployment Setup   ║"
echo "╚══════════════════════════════════════╝"
echo ""

# --- 1. Install Docker if not present ---
if ! command -v docker &>/dev/null; then
    echo "[1/6] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "  ✓ Docker installed"
else
    echo "[1/6] Docker already installed ($(docker --version | cut -d' ' -f3))"
fi

# --- 2. Ensure docker compose plugin ---
if ! docker compose version &>/dev/null; then
    echo "[2/6] Installing Docker Compose plugin..."
    apt-get update -qq && apt-get install -y -qq docker-compose-plugin
    echo "  ✓ Docker Compose installed"
else
    echo "[2/6] Docker Compose already installed"
fi

# --- 3. Set up project directory ---
echo "[3/6] Setting up project at $PROJECT_DIR..."
mkdir -p "$PROJECT_DIR"

# Copy files if running from repo checkout
if [ -f "docker-compose.yml" ]; then
    cp docker-compose.yml Dockerfile pyproject.toml alembic.ini "$PROJECT_DIR/"
    cp -r api/ alembic/ deploy/ "$PROJECT_DIR/"
fi

cd "$PROJECT_DIR"

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    echo "  Creating .env from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
    else
        cat > .env <<'ENVEOF'
DEV_MODE=false
USE_MOCK_PROVIDERS=false
POSTGRES_PASSWORD=changeme
ENVEOF
    fi
    echo "  ⚠ EDIT .env with your credentials before proceeding!"
    echo "    Required: R2 credentials, POSTGRES_PASSWORD"
    echo ""
fi

# --- 4. Build and pull images ---
echo "[4/6] Building Docker images..."
docker compose build --pull
echo "  ✓ Images built"

# --- 5. Start services and run migrations ---
echo "[5/6] Starting services..."
docker compose up -d
echo "  Waiting for PostgreSQL to be ready..."
sleep 5

# Run Alembic migrations inside the container
echo "  Running database migrations..."
docker compose exec -T cloud python -m alembic upgrade head 2>/dev/null || \
    echo "  (migrations skipped — tables auto-created on startup)"
echo "  ✓ Services started"

# --- 6. Health check ---
echo "[6/6] Running health check..."
MAX_RETRIES=10
for i in $(seq 1 $MAX_RETRIES); do
    HEALTH=$(curl -sf http://localhost:8200/health 2>/dev/null || echo "")
    if echo "$HEALTH" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d['status']=='ok' else 1)" 2>/dev/null; then
        echo "  ✓ Health check passed"
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        echo "  ✗ Health check failed after $MAX_RETRIES attempts"
        echo "  Check logs: docker compose logs cloud"
        exit 1
    fi
    echo "  Attempt $i/$MAX_RETRIES — waiting..."
    sleep 3
done

# --- Status ---
echo ""
echo "╔══════════════════════════════════════╗"
echo "║         Deployment Complete          ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "Services:"
docker compose ps --format "  {{.Name}}: {{.Status}}"
echo ""
echo "Endpoints:"
echo "  Health:  http://localhost:8200/health"
echo "  Status:  http://localhost:8200/api/v1/status"
echo "  API:     http://localhost:8200/api/v1/"
echo ""
echo "Next steps:"
echo "  1. Set up SSL:  sudo ./deploy/scripts/setup-ssl.sh $DOMAIN"
echo "  2. Set up nginx: copy deploy/nginx.conf to /etc/nginx/sites-available/"
echo "  3. Configure DNS: point $DOMAIN to this server's IP"
echo ""
