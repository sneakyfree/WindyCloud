#!/usr/bin/env bash
# Health check for Windy Cloud — used by Docker and monitoring
set -euo pipefail

RESPONSE=$(curl -sf http://localhost:8200/health 2>/dev/null)
STATUS=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null)

if [ "$STATUS" = "ok" ]; then
    exit 0
else
    echo "Health check failed: $RESPONSE"
    exit 1
fi
