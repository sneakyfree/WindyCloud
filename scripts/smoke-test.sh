#!/usr/bin/env bash
# Windy Cloud smoke test — hit the critical paths on a running
# deployment and exit non-zero if any of them regress.
#
# Usage:
#   scripts/smoke-test.sh [BASE_URL]
#
# BASE_URL defaults to http://localhost:8200. Required env:
#   SERVICE_TOKEN — same secret the API uses for X-Service-Token
#   USER_JWT      — a Bearer JWT the API accepts (Windy Pro-signed)
#
# Exit codes:
#   0 — all checks passed
#   1 — a check failed (see stderr for which)
#   2 — prereq missing (env var, curl, jq)
#
# Called from CI post-deploy (see DEPLOY.md §6) and from operators
# running a deploy-gate locally. Keep it fast (< 10s) and silent on
# success so the deploy log stays readable.

set -euo pipefail

BASE_URL="${1:-http://localhost:8200}"
IDENTITY_ID="${SMOKE_IDENTITY_ID:-smoke-$(date +%s)-$RANDOM}"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "smoke-test: missing required command: $1" >&2
    exit 2
  }
}

need curl
need jq

if [[ -z "${SERVICE_TOKEN:-}" ]]; then
  echo "smoke-test: SERVICE_TOKEN is required (set to match the API's X-Service-Token)" >&2
  exit 2
fi
if [[ -z "${USER_JWT:-}" ]]; then
  echo "smoke-test: USER_JWT is required (any Bearer token the API accepts)" >&2
  exit 2
fi

pass() { printf '  \033[32mok\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mfail\033[0m %s\n' "$1" >&2; exit 1; }

echo "smoke-test: BASE_URL=$BASE_URL identity=$IDENTITY_ID"

# -------- 1. /health --------------------------------------------------
# Public endpoint; no auth. Should return {"status":"ok",...}.

status="$(curl -fsS --max-time 5 "$BASE_URL/health" | jq -r '.status')" \
  || fail "/health unreachable"
[[ "$status" == "ok" ]] || fail "/health returned status=$status (expected ok)"
pass "/health"

# -------- 2. /api/v1/billing/allocate ---------------------------------
# Service-token endpoint. Provisions (or refreshes) a free-tier plan
# for a synthetic identity. Idempotent, so reruns of this script don't
# leave cruft behind beyond one row per smoke identity.

allocate_body="$(jq -nc --arg id "$IDENTITY_ID" '{windy_identity_id: $id, tier: "free"}')"
allocate_status="$(curl -sS -o "$TMPDIR/allocate.json" -w '%{http_code}' \
  -X POST "$BASE_URL/api/v1/billing/allocate" \
  -H "Content-Type: application/json" \
  -H "X-Service-Token: $SERVICE_TOKEN" \
  -d "$allocate_body" || echo 000)"
[[ "$allocate_status" == "200" ]] \
  || fail "/billing/allocate returned $allocate_status (expected 200) — body: $(cat "$TMPDIR/allocate.json")"
quota="$(jq -r '.quota_bytes' "$TMPDIR/allocate.json")"
[[ "$quota" =~ ^[0-9]+$ ]] && [[ "$quota" -gt 0 ]] \
  || fail "/billing/allocate returned non-positive quota_bytes=$quota"
pass "/billing/allocate (tier=free, quota=$quota bytes)"

# -------- 3. storage upload + download roundtrip ----------------------
# User-JWT path. Uploads a small file, confirms it appears in /files,
# then downloads it and asserts byte-for-byte equality.

payload="windy-cloud smoke $(date -u +%Y-%m-%dT%H:%M:%SZ) $RANDOM"
echo "$payload" > "$TMPDIR/in.txt"

upload_status="$(curl -sS -o "$TMPDIR/upload.json" -w '%{http_code}' \
  -X POST "$BASE_URL/api/v1/storage/upload" \
  -H "Authorization: Bearer $USER_JWT" \
  -F "file=@$TMPDIR/in.txt" \
  -F "product=smoke-test" || echo 000)"
[[ "$upload_status" == "200" ]] \
  || fail "/storage/upload returned $upload_status — body: $(cat "$TMPDIR/upload.json")"
file_id="$(jq -r '.file_id' "$TMPDIR/upload.json")"
[[ -n "$file_id" && "$file_id" != "null" ]] || fail "/storage/upload returned no file_id"
pass "/storage/upload (file_id=$file_id)"

list_status="$(curl -sS -o "$TMPDIR/list.json" -w '%{http_code}' \
  "$BASE_URL/api/v1/storage/files?product=smoke-test" \
  -H "Authorization: Bearer $USER_JWT" || echo 000)"
[[ "$list_status" == "200" ]] || fail "/storage/files returned $list_status"
jq -e --arg id "$file_id" '.files[] | select(.file_id == $id)' "$TMPDIR/list.json" \
  > /dev/null \
  || fail "uploaded file_id=$file_id not found in /storage/files"
pass "/storage/files (found $file_id)"

download_status="$(curl -sS -o "$TMPDIR/out.txt" -w '%{http_code}' \
  "$BASE_URL/api/v1/storage/files/$file_id" \
  -H "Authorization: Bearer $USER_JWT" || echo 000)"
[[ "$download_status" == "200" ]] \
  || fail "/storage/files/$file_id returned $download_status"

cmp -s "$TMPDIR/in.txt" "$TMPDIR/out.txt" \
  || fail "downloaded bytes differ from uploaded bytes"
pass "/storage download roundtrip (bytes match)"

echo "smoke-test: all checks passed"
