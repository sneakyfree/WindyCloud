#!/usr/bin/env bash
# Windy Cloud — AWS EC2 Deployment Setup
#
# Runs ON the EC2 instance (via user-data or SSH).
# Assumes Ubuntu 24.04 AMI on t3.medium.
#
# Usage:
#   1. Launch EC2 instance (t3.medium, Ubuntu 24.04, 30GB EBS)
#   2. SSH in: ssh -i key.pem ubuntu@<ip>
#   3. curl -fsSL https://raw.githubusercontent.com/sneakyfree/WindyCloud/main/deploy/aws-setup.sh | sudo bash
#
# Or paste this script as EC2 user-data for automated provisioning.

set -euo pipefail

DOMAIN="${WINDY_CLOUD_DOMAIN:-cloud.windyfly.ai}"
PROJECT_DIR="/opt/windy-cloud"

echo "╔══════════════════════════════════════════╗"
echo "║   Windy Cloud — AWS EC2 Setup            ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Domain: $DOMAIN"
echo ""

# --- 1. System updates ---
echo "[1/8] Updating system packages..."
apt-get update -qq
apt-get upgrade -y -qq
echo "  ✓ System updated"

# --- 2. Install Docker ---
echo "[2/8] Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker ubuntu
    systemctl enable docker
    systemctl start docker
    echo "  ✓ Docker installed"
else
    echo "  Docker already installed"
fi

# --- 3. Install nginx ---
echo "[3/8] Installing nginx..."
apt-get install -y -qq nginx
systemctl enable nginx
echo "  ✓ nginx installed"

# --- 4. Clone/update repo ---
echo "[4/8] Setting up project..."
if [ -d "$PROJECT_DIR/.git" ]; then
    cd "$PROJECT_DIR"
    git pull --ff-only
else
    git clone https://github.com/sneakyfree/WindyCloud.git "$PROJECT_DIR"
    cd "$PROJECT_DIR"
fi

# Create .env if missing
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "  ⚠  EDIT /opt/windy-cloud/.env before continuing!"
    echo "     Required:"
    echo "       - POSTGRES_PASSWORD (strong random value)"
    echo "       - R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY"
    echo "       - AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (for VPS/compute)"
    echo ""
fi

# --- 5. Configure security (UFW) ---
echo "[5/8] Configuring firewall..."
if command -v ufw &>/dev/null; then
    ufw allow 22/tcp    # SSH
    ufw allow 80/tcp    # HTTP (certbot + redirect)
    ufw allow 443/tcp   # HTTPS
    ufw allow 8200/tcp  # Direct API (optional, remove after nginx is set up)
    ufw --force enable
    echo "  ✓ Firewall configured (22, 80, 443, 8200)"
fi

# --- 6. Build and start services ---
echo "[6/8] Building and starting services..."
cd "$PROJECT_DIR"
docker compose build --pull
docker compose up -d
echo "  Waiting for services to start..."
sleep 10

# Run migrations
docker compose exec -T cloud python -m alembic upgrade head 2>/dev/null || \
    echo "  (migrations skipped — tables auto-created on startup)"
echo "  ✓ Services running"

# --- 7. Configure nginx + SSL ---
echo "[7/8] Configuring nginx + SSL..."

# Install nginx config
cp deploy/nginx.conf /etc/nginx/sites-available/windy-cloud
ln -sf /etc/nginx/sites-available/windy-cloud /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Temporary HTTP-only config for certbot
cat > /etc/nginx/sites-available/windy-cloud-bootstrap <<NGINX_EOF
server {
    listen 80;
    server_name $DOMAIN;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        proxy_pass http://127.0.0.1:8200;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX_EOF
ln -sf /etc/nginx/sites-available/windy-cloud-bootstrap /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# Get SSL certificate
if ! command -v certbot &>/dev/null; then
    apt-get install -y -qq certbot python3-certbot-nginx
fi

echo "  Requesting SSL certificate for $DOMAIN..."
certbot certonly \
    --nginx \
    -d "$DOMAIN" \
    --email admin@windycloud.com \
    --agree-tos \
    --non-interactive 2>/dev/null && {
    # Switch to full SSL config
    rm -f /etc/nginx/sites-enabled/windy-cloud-bootstrap
    nginx -t && systemctl reload nginx
    systemctl enable certbot.timer 2>/dev/null || true
    echo "  ✓ SSL configured"
} || {
    echo "  ⚠ SSL certificate request failed (DNS not pointed yet?)"
    echo "    Run later: sudo certbot certonly --nginx -d $DOMAIN"
    echo "    Then: sudo rm /etc/nginx/sites-enabled/windy-cloud-bootstrap"
    echo "    Then: sudo systemctl reload nginx"
}

# --- 8. Health check ---
echo "[8/8] Health check..."
MAX_RETRIES=5
for i in $(seq 1 $MAX_RETRIES); do
    if curl -sf http://localhost:8200/health | python3 -c "
import sys, json
d = json.load(sys.stdin)
assert d['status'] == 'ok', d
print('  ✓ Health check passed:', json.dumps(d))
" 2>/dev/null; then
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        echo "  ✗ Health check failed. Check: docker compose logs cloud"
        exit 1
    fi
    sleep 3
done

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║        AWS Deployment Complete           ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Services:"
docker compose ps --format "  {{.Name}}: {{.Status}}" 2>/dev/null || docker compose ps
echo ""
echo "Endpoints:"
echo "  Health:    http://$(curl -s ifconfig.me):8200/health"
echo "  API:       https://$DOMAIN/api/v1/status"
echo "  Dashboard: https://$DOMAIN/"
echo ""
echo "Next steps:"
echo "  1. Point DNS for $DOMAIN to this server's Elastic IP"
echo "  2. Edit /opt/windy-cloud/.env with real credentials"
echo "  3. Restart: cd /opt/windy-cloud && docker compose restart"
echo ""
