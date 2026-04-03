#!/usr/bin/env bash
# Seed test data into a running Windy Cloud instance
set -euo pipefail

BASE_URL="${WINDY_CLOUD_URL:-http://localhost:8200}"
TOKEN="${WINDY_CLOUD_TOKEN:-test-token}"

echo "Seeding Windy Cloud at $BASE_URL"

# Check health
echo -n "Health check... "
curl -sf "$BASE_URL/health" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])"

# Upload test files
echo "Uploading test files..."

curl -sf -X POST "$BASE_URL/api/v1/storage/upload" \
    -H "Authorization: Bearer $TOKEN" \
    -F "file=@scripts/seed.sh" \
    -F "product=windy_code" \
    -F "file_type=settings" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Uploaded: {d[\"file_id\"]} ({d[\"size\"]} bytes)')"

echo "Creating test archives..."

echo '{"theme":"dark","fontSize":14}' | curl -sf -X POST "$BASE_URL/api/v1/archive/code-settings" \
    -H "Authorization: Bearer $TOKEN" \
    -F "file=@-;filename=settings.json;type=application/json" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Archive: {d[\"product\"]}/{d[\"type\"]} ({d[\"size\"]} bytes)')"

echo ""
echo "Checking usage..."
curl -sf "$BASE_URL/api/v1/storage/usage" \
    -H "Authorization: Bearer $TOKEN" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  Storage: {d[\"used_bytes\"]} bytes / {d[\"quota_bytes\"]} bytes ({d[\"used_percent\"]}%)')"

echo ""
echo "Seed complete."
