# Windy Cloud

**Your digital life, unified — one cloud for storage, compute, and servers across the entire Windy ecosystem.**

**Repo:** [github.com/sneakyfree/WindyCloud](https://github.com/sneakyfree/WindyCloud)

---

## The Problem

Every Windy product stores data separately — recordings in Pro, messages in Chat, emails in Mail, memories in Fly. There's no central place to browse, back up, or restore your data. And when your laptop is on fire, local voice-to-text crawls.

## The Solution

Windy Cloud is the **iCloud of the Windy ecosystem**. Three pillars:

1. **Storage** — Cold storage for all products. Archive chat backups, mail exports, agent memories, recordings. Browse from a web portal.
2. **Compute** — Cloud GPU for speech-to-text. Pay per minute, way faster than local. Start on RunPod, grow into own GPU cluster.
3. **Servers** — VPS hosting on AWS. Provision cloud servers through the Windy platform.

## Quick Start

### Development (SQLite)

```bash
# Clone
git clone https://github.com/sneakyfree/WindyCloud.git windy-cloud
cd windy-cloud

# One-command dev start (creates venv, installs deps, starts server)
./scripts/dev.sh

# Or manually:
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn api.app.main:app --reload --port 8200
```

No env vars needed — defaults to SQLite + local disk storage.

### Production (PostgreSQL)

```bash
# Set DATABASE_URL in .env
cp .env.example .env
# Edit .env:
#   DATABASE_URL=postgresql+asyncpg://user:pass@localhost/windy_cloud

# Run migrations
alembic upgrade head

# Start with Docker
docker compose up -d
```

- API docs: http://localhost:8200/docs
- Health: http://localhost:8200/health
- Status: http://localhost:8200/api/v1/status

### SSL Setup (VPS)

```bash
# On the VPS (as root)
sudo ./deploy/scripts/setup-ssl.sh cloud.windycloud.com
```

## API

All endpoints require `Authorization: Bearer <jwt>` (except health/status/plans).

### Storage

```
POST   /api/v1/storage/upload          Upload file (multipart)
GET    /api/v1/storage/files           List files (paginated, filterable)
GET    /api/v1/storage/files/{id}      Download file
DELETE /api/v1/storage/files/{id}      Delete file
GET    /api/v1/storage/usage           Storage usage + quota
GET    /api/v1/storage/breakdown       Per-product storage breakdown for dashboards
GET    /api/v1/storage/export          ZIP of every file for GDPR data export
GET    /api/v1/storage/health          Provider health (public)
GET    /api/v1/storage/plans           Storage plans + pricing (public)
```

### Archive (product-specific)

```
POST   /api/v1/archive/chat                         Encrypted chat backups (retention support)
POST   /api/v1/archive/mail                         Mail server backups
POST   /api/v1/archive/agent                        Agent database backups
POST   /api/v1/archive/recordings                   Recording archives
POST   /api/v1/archive/code-settings                IDE settings sync
POST   /api/v1/archive/migrate                      Batch metadata registration (service-token)
GET    /api/v1/archive/retrieve/{product}/{path}    Fetch a previously archived file
```

### Compute (STT)

```
POST   /api/v1/compute/stt             Transcribe audio (multipart)
GET    /api/v1/compute/stt/{job_id}    Get job status/result
GET    /api/v1/compute/usage           Compute usage this month
GET    /api/v1/compute/models          Available models + pricing (public)
```

### Servers (VPS)

```
POST   /api/v1/servers/create          Provision server
GET    /api/v1/servers                 List servers
GET    /api/v1/servers/{id}            Server details (live status)
POST   /api/v1/servers/{id}/action     Start / stop / reboot
DELETE /api/v1/servers/{id}            Terminate server
POST   /api/v1/servers/deploy-fly      Fly.io deploy orchestration
GET    /api/v1/servers/plans           Available plans + pricing (public)
```

### Billing

```
GET    /api/v1/billing/usage           Combined usage summary for the current user
GET    /api/v1/billing/history         Billing history (from daily snapshots)
GET    /api/v1/billing/estimate        Current period cost estimate
GET    /api/v1/billing/summary         Agent-friendly usage summary (windy-agent)
GET    /api/v1/billing/plan            Current user's storage plan
POST   /api/v1/billing/plan/upgrade    Switch plan (called after Stripe success)
POST   /api/v1/billing/sync            Service-to-service usage pull (windy-pro for Stripe)
POST   /api/v1/billing/allocate        Provision a plan (service-token, idempotent)
```

### Analytics / sync / export

```
GET    /api/v1/analytics/daily         Daily counters for dashboards (auth'd)
GET    /api/v1/analytics/summary       Aggregate analytics summary
GET    /api/v1/sync/status             Product-sync state for the current user
POST   /api/v1/sync/offer-backup       Post-hatch: queue first-backup + push notification (idempotent)
POST   /api/v1/export/my-data          Kick off a GDPR data-export job
GET    /api/v1/export/{job_id}         Poll data-export job status
```

### Deep links (Wave 8)

```
GET    /api/v1/deeplink/resolve        Resolve a windycloud://<target> URL
GET    /api/v1/deeplink/manifest       Enumerate supported deep-link targets
```

### Identity bridge

```
POST   /api/v1/identity/link-passport             Link passport ↔ windy identity
GET    /api/v1/identity/by-passport/{passport}    Resolve passport to identity
```

### Webhooks (inbound)

```
POST   /api/v1/webhooks/identity/created   Windy Pro → provisions a UserPlan (HMAC)
POST   /api/v1/webhooks/passport/revoked   Eternitas → freezes plan (ES256)
POST   /api/v1/webhooks/passport/reinstated Eternitas → un-freezes plan (ES256)
POST   /api/v1/webhooks/trust/changed      Eternitas → flushes local trust cache (HMAC)
POST   /api/v1/webhooks/stripe             Stripe → subscription + invoice events (Stripe-Signature)
```

## Trust API integration (Wave 4)

Windy Cloud gates quota + uploads through the Eternitas Trust API. Contract
reference is **the single source of truth** and lives with the producer:

> [`/Users/thewindstorm/eternitas/docs/trust-api.md`](../eternitas/docs/trust-api.md)

### What Cloud calls

- `GET {ETERNITAS_URL}/api/v1/trust/{passport}` on every billing-allocate
  where a passport is provided, and on every authed upload when the caller
  has a passport linked via the identity bridge.
- Responses are cached in-process for 5 minutes (or whatever
  `cache_ttl_seconds` the response suggests, whichever is smaller).
- Cache is invalidated proactively on `trust.changed` deliveries (see
  `routes/webhooks.py`) so stale trust doesn't linger.

### Gating rules

| Signal | Result |
|---|---|
| `status = active` + `tier_multiplier > 0` | Upload allowed, quota = `base_tier_quota * multiplier` |
| `status = suspended` | Upload → 403 `suspended_account` |
| `status = revoked` | Upload → 403 `frozen_account` |
| `band = critical` (multiplier 0.0) | Quota allocated at 0 bytes — effectively blocked |
| No passport linked (human identity) | Base quota, multiplier 1.0, trust API **not** called |

### Env vars

| Var | Default | Purpose |
|---|---|---|
| `ETERNITAS_URL` | `http://localhost:8500` | Base URL for Trust API + webhook dispatch. See `deploy/docs/env-vars.md`. |
| `ETERNITAS_USE_MOCK` | `false` | When `true`, `TrustClient.get_trust()` returns `None` without hitting HTTP. Use for offline dev/CI. |
| `ETERNITAS_WEBHOOK_SECRET` | — | HMAC-SHA256 secret for verifying `X-Eternitas-Signature` on `trust.changed` + `passport.*` webhooks. Must match the `webhook_secret` Eternitas returned at platform registration. |

### Running the live integration tests

```bash
# 1. Start Eternitas (postgres + redis + uvicorn)
cd /Users/thewindstorm/eternitas && scripts/dev-start.sh

# 2. Point Cloud at it + name a seeded passport
export ETERNITAS_URL=http://localhost:8200
export ETERNITAS_TEST_PASSPORT=ET-00001

# 3. Run
cd /Users/thewindstorm/windy-cloud
uv run pytest api/tests/integration/test_trust_live.py -v
```

Tests auto-skip if Eternitas isn't reachable or `ETERNITAS_TEST_PASSPORT`
isn't set, so CI against a network-isolated runner stays green.

## Architecture

Hub-and-spoke: each product keeps hot storage locally, archives to Cloud for long-term cold storage.

```
Windy Pro ──┐
Windy Chat ─┤
Windy Mail ─┼──► Windy Cloud (R2 + RunPod GPU + AWS EC2)
Windy Fly ──┤
Windy Code ─┘
```

Auth via Windy Pro's JWKS — no separate Cloud login. Agents auth via Eternitas EPT tokens.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Framework | FastAPI (Python 3.11+) |
| Storage | Cloudflare R2 (boto3) / local disk fallback |
| GPU Compute | RunPod Serverless (faster-whisper) |
| VPS | AWS EC2 (5 plans, 3 regions) |
| Auth | RS256/ES256 JWT via JWKS |
| Database | SQLite (dev) / PostgreSQL + asyncpg (prod) |
| Migrations | Alembic (async) |
| Container | Docker + docker-compose |
| CI/CD | GitHub Actions |
| SSL | Let's Encrypt (certbot) |

## Database Migrations

```bash
# Apply all migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "description"

# Check current version
alembic current
```

## Testing

```bash
source .venv/bin/activate
python -m pytest api/tests/ -v
```

## Deployment

```bash
# Docker (production)
docker compose up -d

# Or deploy to VPS (72.60.118.54)
# CI/CD auto-deploys on push to main
```

Nginx config in `deploy/nginx.conf`. SSL via Let's Encrypt — run `deploy/scripts/setup-ssl.sh`.

## Key Documents

- [DNA_STRAND_MASTER_PLAN.md](DNA_STRAND_MASTER_PLAN.md) — Complete architecture blueprint
- [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) — Per-product integration docs
- [GAP_ANALYSIS.md](GAP_ANALYSIS.md) — Current gap analysis and ship-readiness

## Status

**Phase:** 3 — All three pillars implemented
**Port:** 8200
**Domain:** cloud.windycloud.com
