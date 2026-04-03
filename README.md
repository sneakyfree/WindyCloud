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
sudo ./deploy/scripts/setup-ssl.sh cloud.windyfly.ai
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
GET    /api/v1/storage/health          Provider health (public)
GET    /api/v1/storage/plans           Storage plans + pricing (public)
```

### Archive (product-specific)

```
POST   /api/v1/archive/chat            Encrypted chat backups (retention support)
POST   /api/v1/archive/mail            Mail server backups
POST   /api/v1/archive/agent           Agent database backups
POST   /api/v1/archive/recordings      Recording archives
POST   /api/v1/archive/code-settings   IDE settings sync
```

### Compute (STT)

```
POST   /api/v1/compute/stt             Transcribe audio (multipart)
GET    /api/v1/compute/stt/{job_id}    Get job status/result
GET    /api/v1/compute/usage           Compute usage this month
GET    /api/v1/compute/models          Available models + pricing
```

### Servers (VPS)

```
POST   /api/v1/servers/create          Provision server
GET    /api/v1/servers                  List servers
GET    /api/v1/servers/{id}            Server details (live status)
POST   /api/v1/servers/{id}/action     Start / stop / reboot
DELETE /api/v1/servers/{id}            Terminate server
GET    /api/v1/servers/plans           Available plans + pricing (public)
```

### Billing

```
GET    /api/v1/billing/usage           Combined usage summary
GET    /api/v1/billing/history         Billing history (from daily snapshots)
GET    /api/v1/billing/estimate        Current period estimate
```

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
**Domain:** cloud.windyfly.ai
