#!/usr/bin/env bash
# Setup Let's Encrypt SSL for Windy Cloud
# Usage: sudo ./deploy/scripts/setup-ssl.sh [domain]

set -euo pipefail

DOMAIN="${1:-cloud.windyfly.ai}"
EMAIL="${2:-admin@thewindstorm.uk}"

echo "=== Windy Cloud SSL Setup ==="
echo "Domain: $DOMAIN"
echo "Email:  $EMAIL"
echo ""

# Install certbot if not present
if ! command -v certbot &>/dev/null; then
    echo "Installing certbot..."
    apt-get update -qq
    apt-get install -y -qq certbot python3-certbot-nginx
fi

# Install nginx if not present
if ! command -v nginx &>/dev/null; then
    echo "Installing nginx..."
    apt-get update -qq
    apt-get install -y -qq nginx
fi

# Copy nginx config
echo "Installing nginx config..."
cp deploy/nginx.conf /etc/nginx/sites-available/windy-cloud
ln -sf /etc/nginx/sites-available/windy-cloud /etc/nginx/sites-enabled/windy-cloud

# Remove default site if it exists
rm -f /etc/nginx/sites-enabled/default

# Test nginx config (without SSL certs first — certbot will handle this)
# We need a temporary config for the initial certbot run
cat > /etc/nginx/sites-available/windy-cloud-temp <<EOF
server {
    listen 80;
    server_name $DOMAIN;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}
EOF
ln -sf /etc/nginx/sites-available/windy-cloud-temp /etc/nginx/sites-enabled/windy-cloud-temp
nginx -t && systemctl reload nginx

# Get certificate
echo "Requesting SSL certificate..."
certbot certonly \
    --nginx \
    -d "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --non-interactive

# Remove temp config, enable full config
rm -f /etc/nginx/sites-enabled/windy-cloud-temp
rm -f /etc/nginx/sites-available/windy-cloud-temp

# Test and reload with full SSL config
nginx -t && systemctl reload nginx

# Setup auto-renewal
echo "Setting up auto-renewal..."
systemctl enable certbot.timer 2>/dev/null || true

echo ""
echo "=== SSL setup complete ==="
echo "Certificate:  /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
echo "Private key:  /etc/letsencrypt/live/$DOMAIN/privkey.pem"
echo "Auto-renewal: enabled via certbot.timer"
echo ""
echo "Test with: curl -I https://$DOMAIN/health"
