# DNA_STRAND_MASTER_PLAN.md — Windy Cloud

**Version:** 0.1.0
**Created:** 2026-04-02
**Last Updated:** 2026-04-02
**Authors:** Grant Whitmer + Claude Opus 4.6
**Philosophy:** Your digital life, unified — one cloud for all Windy products, like iCloud for the Windy ecosystem.

---

## TERMINOLOGY STANDARD

| Internal Term | User-Facing Term | Meaning |
|---------------|-----------------|---------|
| `windy_identity_id` | Windy Account | Cross-product UUID from Windy Pro account-server |
| Cold storage | Windy Cloud | Long-term archive accessible from web portal |
| Hot storage | (per-product) | Each product's own local/real-time data |
| Compute job | Cloud Processing | GPU-accelerated tasks (STT, etc.) |
| VPS instance | Cloud Server | User-provisioned virtual private server |
| R2 bucket | (invisible) | Cloudflare R2 — the storage backend |
| Provider | (invisible) | Swappable backend (RunPod, AWS, etc.) |
| Hub-and-spoke | (invisible) | Architecture: Cloud is hub, products are spokes |
| Passport | Agent ID | Eternitas-issued bot identity |

---

## VISION

Windy Cloud is the **iCloud of the Windy ecosystem**. Every Windy product keeps its own hot storage (Matrix messages in Synapse, email in Stalwart, agent memories in SQLite), but all of them archive to Windy Cloud for long-term cold storage, cross-device sync, and backup.

Beyond storage, Windy Cloud provides **GPU compute** for cloud-based voice-to-text (far superior to local STT when the user's machine is under load) and **VPS servers** for users who want hosted infrastructure.

The three pillars:

1. **Storage** — Cloudflare R2 cold storage. Products push archives, users browse from a web portal. Like iCloud Drive + iCloud Backup combined.
2. **Compute** — GPU inference on demand. Start with AWS pay-per-use GPUs (or RunPod Serverless). Mark up enough to cover costs. User only pays when they use it. Scale to own GPU cluster farm when volume justifies it.
3. **Servers** — VPS hosting on AWS EC2. Users provision cloud servers through Windy Cloud. Start on AWS, migrate to own hardware when we outgrow it.

**The business model:**
- **Storage**: Tiered monthly plans (500MB free, 5GB/$2, 50GB/$5, 200GB/$10)
- **Compute**: Per-minute GPU pricing with markup (e.g., RunPod costs $0.01/min, charge $0.03/min)
- **Servers**: Monthly pricing based on instance size

All billing tracked per `windy_identity_id`, managed through Windy Pro.

---

## ECOSYSTEM CONTEXT

Windy Cloud is one of 8 products in the Windy ecosystem, plus the Eternitas identity layer:

| Product | Repo | Role | Cloud Integration |
|---------|------|------|-------------------|
| **Windy Pro** (Windy Word) | `sneakyfree/windy-pro` | Identity hub, account-server, recording app | Auth authority (JWKS), existing R2 adapter to migrate |
| **Windy Chat** | `sneakyfree/windy-chat` | Matrix-based messaging | Encrypted chat backups to Cloud |
| **Windy Mail** | `sneakyfree/windy-mail` | Stalwart-based email | Mail archive, attachment storage |
| **Windy Fly** | `sneakyfree/windy-agent` | AI agent platform | Agent memory backup, database sync |
| **Windy Code** | `sneakyfree/windy-code` | VS Code fork IDE | Settings sync, extension storage |
| **Windy Mobile** | `sneakyfree/windy-pro-mobile` | React Native app | Recording sync, offline cache |
| **Windy Cloud** | `sneakyfree/WindyCloud` | **THIS REPO** | Hub for all storage + compute |
| **Eternitas** | `sneakyfree/eternitas` | Bot identity & verification | Soul Key vault backup (encrypted) |

### Hub-and-Spoke Architecture

```
                         ┌─────────────────┐
                         │   Windy Cloud    │
                         │  (Cold Storage)  │
                         │   ┌─────────┐   │
                         │   │   R2    │   │
                         │   └─────────┘   │
                         │   ┌─────────┐   │
                         │   │  AWS    │   │
                         │   │  GPU    │   │
                         │   └─────────┘   │
                         │   ┌─────────┐   │
                         │   │  AWS    │   │
                         │   │  EC2    │   │
                         │   └─────────┘   │
                         └────────┬────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
              ┌─────┴─────┐ ┌────┴────┐ ┌─────┴─────┐
              │ Windy Pro │ │  Windy  │ │  Windy    │
              │ (Account  │ │  Chat   │ │  Mail     │
              │  Server)  │ │(Synapse)│ │(Stalwart) │
              │  JWKS     │ │  Hot    │ │   Hot     │
              │  Auth Hub │ │ Storage │ │  Storage  │
              └───────────┘ └─────────┘ └───────────┘
                    │             │             │
              ┌─────┴─────┐ ┌────┴────┐ ┌─────┴─────┐
              │ Windy Fly │ │  Windy  │ │  Windy    │
              │  (Agent)  │ │  Code   │ │  Mobile   │
              │  SQLite   │ │  IDE    │ │  React    │
              │  Hot DB   │ │Settings │ │  Native   │
              └───────────┘ └─────────┘ └───────────┘
```

**Data flow:** Each product stores real-time data locally (hot). On a schedule or user action, products push archives/backups to Windy Cloud (cold). Users can browse, download, or restore from the Cloud web portal.

### Auth Flow

```
User → Windy Pro (login) → JWT with windy_identity_id
                                    │
                                    ▼
                            Windy Cloud API
                            validates via JWKS
                            at Pro's /.well-known/jwks.json
```

- **No separate Cloud login.** Users authenticate through Windy Pro. Cloud validates JWTs using Pro's public JWKS endpoint.
- **Service-to-service:** Products authenticate with `client_credentials` grant from Pro.
- **Agent uploads:** Windy Fly agents authenticate with their Eternitas passport token (EPT), validated via Eternitas JWKS.

---

## CRITICAL PATH TO MVP

```
Phase 0 (Now)           Phase 1 (Week 1-2)        Phase 2 (Week 3-4)
─────────────────       ──────────────────        ──────────────────
Repo skeleton     ───►  Storage API         ───►  Compute API (STT)
DNA Strand              R2 provider               GPU provider
pyproject.toml          Auth middleware            Usage tracking
Docker setup            File CRUD                 Billing stubs
                        Health endpoint           Web portal v1
                        Agent backup endpoint
                        Windy Fly integration

Phase 3 (Month 2)       Phase 4 (Month 3+)
──────────────────       ──────────────────
VPS provisioning        GPU cluster migration
AWS EC2 provider        Own hardware
Server management       Advanced portal
Billing integration     Retention policies
All products archiving  Data lifecycle rules
```

**What blocks what:**
1. Auth middleware (JWKS validation) blocks everything
2. R2 provider blocks storage routes
3. Storage routes block product integrations
4. GPU provider blocks compute routes
5. AWS EC2 provider blocks VPS routes

---

## CONFIRMED TECHNICAL DECISIONS

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Language | **Python / FastAPI** | Python-first ecosystem, matches Windy Fly & Eternitas |
| 2 | Storage backend | **Cloudflare R2** | S3-compatible, zero egress fees, existing ecosystem usage |
| 3 | GPU compute (start) | **RunPod Serverless or AWS SageMaker** | Pay-per-second, no idle costs, swap later |
| 4 | GPU compute (later) | **Own GPU cluster** | When volume justifies capex |
| 5 | VPS hosting | **AWS EC2** | Start on AWS, migrate to own hardware later |
| 6 | Auth | **JWKS from Windy Pro** | No separate login, validate JWTs via Pro's public keys |
| 7 | Database | **SQLite (dev) / PostgreSQL (prod)** | Metadata only — files in R2, not in DB |
| 8 | Agent auth | **Eternitas EPT tokens** | Validated via Eternitas JWKS |
| 9 | Encryption | **Optional AES-256-GCM per file** | User-provided passphrase, zero-knowledge |
| 10 | API style | **REST (not GraphQL)** | Consistency with ecosystem, simpler for agents |
| 11 | Container | **Docker + docker-compose** | Consistent with all other Windy services |
| 12 | SDK for R2 | **boto3** | Python equivalent of the @aws-sdk/client-s3 used in Pro |
| 13 | STT model | **faster-whisper** | Best open-source STT, GPU-accelerated |
| 14 | Billing tracking | **Per-identity usage table** | Track per windy_identity_id, bill through Pro |

---

## TECH STACK

| Component | Technology | Version | Why |
|-----------|-----------|---------|-----|
| Framework | FastAPI | 0.115+ | Async, fast, auto-docs, Python ecosystem |
| Server | Uvicorn | 0.30+ | ASGI, production-grade |
| Storage SDK | boto3 | 1.35+ | S3-compatible, works with R2 |
| HTTP client | httpx | 0.27+ | Async HTTP for provider calls |
| Auth | PyJWT + cryptography | 2.9+ | JWKS validation, RS256 |
| Database | SQLAlchemy + aiosqlite | 2.0+ | Async ORM, metadata storage |
| Encryption | cryptography | 43+ | AES-256-GCM, PBKDF2 |
| Testing | pytest + pytest-asyncio | 8+ | Async test support |
| Container | Docker | 24+ | Deployment |
| CI/CD | GitHub Actions | - | Lint, test, build, push |
| STT Model | faster-whisper | 1.0+ | GPU-accelerated Whisper |

---

## CRITICAL INVARIANTS

1. **Cloud never stores plaintext secrets.** Encryption keys, Soul Keys, passwords — never touch Cloud storage unencrypted. Zero-knowledge where possible.
2. **Auth is always via Windy Pro JWKS.** No separate user database, no separate login. Cloud is a service, not an identity provider.
3. **Providers are swappable.** The API contract (routes) never changes when switching GPU providers (RunPod → SageMaker → own cluster) or storage providers (R2 → S3 → MinIO).
4. **Hot storage stays in products.** Cloud is cold/archive only. Never try to serve real-time Matrix messages or live email from Cloud.
5. **Failures never lose data.** Upload failures retry. Delete failures leave the file. Err on the side of keeping data.
6. **Every file is namespaced.** Path format: `{windy_identity_id}/{product}/{type}/{filename}`. No collisions, no ambiguity.
7. **Quotas are global.** One storage quota per identity across all products, not per-product. Managed in Cloud, reported to Pro.
8. **Agent uploads are first-class.** Windy Fly agents can back up their own databases and memories. Agents authenticate via Eternitas EPT, not user JWT.
9. **The API must be agent-friendly.** Simple REST, clear error messages, no CAPTCHAs, no complex auth flows. An agent should be able to call the API without human help.
10. **Pay-per-use for compute.** No monthly GPU subscriptions. Users pay only for what they use. Track to the second.

---

## API DESIGN

### Storage Endpoints (Pillar 1)

```
POST   /api/v1/storage/upload          Upload file to cloud
GET    /api/v1/storage/files           List user's files (paginated)
GET    /api/v1/storage/files/{file_id} Download file
DELETE /api/v1/storage/files/{file_id} Delete file
GET    /api/v1/storage/usage           Storage usage + quota
GET    /api/v1/storage/health          Health check
```

### Product-Specific Archive Endpoints

```
POST   /api/v1/archive/chat            Archive chat backup (encrypted)
POST   /api/v1/archive/mail            Archive mail backup
POST   /api/v1/archive/agent           Archive agent database
POST   /api/v1/archive/recordings      Archive recordings batch
POST   /api/v1/archive/code-settings   Archive IDE settings
```

### Compute Endpoints (Pillar 2)

```
POST   /api/v1/compute/stt             Cloud speech-to-text
GET    /api/v1/compute/stt/{job_id}    Get STT job result
GET    /api/v1/compute/usage           Compute usage + billing
GET    /api/v1/compute/models          Available models + pricing
```

### Server Endpoints (Pillar 3)

```
POST   /api/v1/servers/create          Provision VPS
GET    /api/v1/servers                  List user's servers
GET    /api/v1/servers/{server_id}      Server details + status
POST   /api/v1/servers/{server_id}/action  Start/stop/reboot
DELETE /api/v1/servers/{server_id}      Terminate server
GET    /api/v1/servers/plans            Available plans + pricing
```

### Billing Endpoints

```
GET    /api/v1/billing/usage           Combined usage summary
GET    /api/v1/billing/history         Billing history
GET    /api/v1/billing/estimate        Current period estimate
```

### Auth

All endpoints require `Authorization: Bearer <jwt>` header.

- **User requests:** JWT from Windy Pro login (RS256, validated via JWKS)
- **Service requests:** JWT from Pro's `client_credentials` grant
- **Agent requests:** EPT token from Eternitas (ES256, validated via Eternitas JWKS)

---

## EXISTING INTEGRATION POINTS

### Windy Fly Agent — Already Has a Client

The agent already has `src/windyfly/integrations/windy_cloud.py` that calls:
- `POST /api/storage/files/upload` — backup agent database (multipart)
- `GET /api/storage/health` — check cloud availability

**Action:** The Cloud API must serve these exact endpoints (or the agent client gets updated to match the final API). The agent client uses Bearer JWT auth and supports optional `encryption_key` for encrypted uploads.

### Windy Pro — Has R2 Adapter to Reference

`account-server/src/services/r2-adapter.ts` is a complete R2 wrapper with:
- Bucket structure: `users/{userId}/{type}/{filename}`
- Upload, download, delete, list, usage, health check
- Metadata tagging: `windy-user-id`, `windy-file-type`, `windy-upload-time`

**Action:** Rewrite this in Python with boto3. Same bucket structure, same metadata tags, compatible paths.

### Windy Chat — Has Encrypted Backup Service

`services/backup/server.js` (port 8104) does AES-256-GCM encrypted backups to R2 with:
- 7-backup retention policy
- PBKDF2 key derivation (100K iterations)
- Zero-knowledge (server can't decrypt)

**Action:** Cloud's `/api/v1/archive/chat` endpoint should accept these encrypted blobs as-is. Don't re-encrypt. The chat service handles encryption, Cloud just stores.

### Windy Mail — Has Backup Scripts

`deploy/scripts/backup-postgres.sh` and `backup-stalwart.sh` use rclone to push to R2.

**Action:** Eventually these scripts should call Cloud's archive API instead of pushing directly to R2. For now, they can coexist.

---

## CLOUD STT — GPU COMPUTE DESIGN

### The Problem

Local speech-to-text (faster-whisper on CPU) works but degrades when the user's machine is under load. Cloud STT offloads to a GPU and returns results fast, regardless of local hardware.

### The Architecture

```
User's App (Windy Pro / Mobile / Code)
         │
         │ POST /api/v1/compute/stt
         │ (audio file + language hint)
         ▼
    ┌─────────────┐
    │ Windy Cloud │
    │   API       │
    │ (FastAPI)   │
    └──────┬──────┘
           │
           ▼
    ┌─────────────┐         ┌─────────────┐
    │   Provider  │ ──────► │  RunPod     │  (Phase 1)
    │   Layer     │         │  Serverless │
    │ (swappable) │         └─────────────┘
    │             │         ┌─────────────┐
    │             │ ──────► │  AWS        │  (Phase 2)
    │             │         │  SageMaker  │
    │             │         └─────────────┘
    │             │         ┌─────────────┐
    │             │ ──────► │  Own GPU    │  (Phase 3)
    │             │         │  Cluster    │
    └─────────────┘         └─────────────┘
```

### Provider Interface

```python
class STTProvider(Protocol):
    async def transcribe(
        self,
        audio: bytes,
        language: str | None = None,
        model: str = "large-v3",
    ) -> TranscriptionResult: ...

    async def health(self) -> bool: ...

    def pricing(self) -> dict:
        """Return per-minute pricing info."""
        ...
```

Every GPU provider implements this interface. The route layer doesn't know or care which provider is active.

### Pricing Model

- Track audio duration per `windy_identity_id`
- Cost = `provider_cost * markup_multiplier`
- Markup multiplier configured in env (e.g., `STT_MARKUP=3.0` → 3x provider cost)
- Free tier: first 10 minutes/month free (configurable)

---

## VPS SERVERS — DESIGN

### Phase 3+ Feature

VPS provisioning is a later phase but the API contract should be designed now.

### Provider Interface

```python
class VPSProvider(Protocol):
    async def create(self, plan: str, region: str, image: str) -> ServerInstance: ...
    async def list(self, identity_id: str) -> list[ServerInstance]: ...
    async def get(self, server_id: str) -> ServerInstance: ...
    async def action(self, server_id: str, action: str) -> ActionResult: ...
    async def delete(self, server_id: str) -> bool: ...
    async def plans(self) -> list[ServerPlan]: ...
```

Start with AWS EC2 (boto3), later add own hardware provider.

---

## FILE INDEX (Target State)

```
windy-cloud/
├── DNA_STRAND_MASTER_PLAN.md       # This file — the blueprint
├── README.md                        # What is this? Quick start.
├── INTEGRATION_GUIDE.md             # Per-product integration docs
├── pyproject.toml                   # Python project config (uv)
├── Dockerfile                       # Production container
├── docker-compose.yml               # Local dev stack
├── .env.example                     # Required env vars
├── .github/
│   └── workflows/
│       ├── ci.yml                   # Lint + test on PR
│       └── deploy.yml               # Build + push container
├── api/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app factory
│   │   ├── config.py                # Settings from env
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── jwks.py              # JWKS fetcher + JWT validator
│   │   │   └── dependencies.py      # FastAPI auth dependencies
│   │   ├── middleware/
│   │   │   ├── __init__.py
│   │   │   └── rate_limit.py        # Per-identity rate limiting
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── storage.py           # File metadata, quota models
│   │   │   ├── compute.py           # STT job, result models
│   │   │   ├── server.py            # VPS instance models
│   │   │   └── billing.py           # Usage tracking models
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── r2.py                # Cloudflare R2 storage adapter
│   │   │   ├── runpod.py            # RunPod serverless STT
│   │   │   ├── sagemaker.py         # AWS SageMaker STT (Phase 2)
│   │   │   ├── aws_ec2.py           # AWS EC2 VPS provisioning
│   │   │   └── local_disk.py        # Local fallback for dev
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── storage.py           # /api/v1/storage/* endpoints
│   │   │   ├── archive.py           # /api/v1/archive/* endpoints
│   │   │   ├── compute.py           # /api/v1/compute/* endpoints
│   │   │   ├── servers.py           # /api/v1/servers/* endpoints
│   │   │   ├── billing.py           # /api/v1/billing/* endpoints
│   │   │   └── health.py            # /health, /api/v1/status
│   │   └── db/
│   │       ├── __init__.py
│   │       ├── engine.py            # SQLAlchemy async engine
│   │       ├── models.py            # ORM models (metadata, usage)
│   │       └── migrations/          # Alembic migrations
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py              # Fixtures, test client
│       ├── test_storage.py
│       ├── test_compute.py
│       ├── test_auth.py
│       └── test_archive.py
├── deploy/
│   ├── nginx.conf                   # Reverse proxy config
│   └── scripts/
│       ├── healthcheck.sh
│       └── migrate.sh
├── docs/
│   ├── ARCHITECTURE.md              # Deep-dive architecture
│   ├── AUTH_FLOW.md                  # JWT validation details
│   └── PROVIDER_GUIDE.md            # How to add new providers
└── scripts/
    ├── dev.sh                       # Start dev server
    └── seed.sh                      # Seed test data
```

---

## ENVIRONMENT VARIABLES

```bash
# === Required ===
# Auth
WINDY_PRO_JWKS_URL=https://windypro.thewindstorm.uk/.well-known/jwks.json
ETERNITAS_JWKS_URL=https://eternitas.thewindstorm.uk/.well-known/eternitas-keys

# R2 Storage
R2_ACCOUNT_ID=your-cloudflare-account-id
R2_ACCESS_KEY_ID=your-r2-access-key
R2_SECRET_ACCESS_KEY=your-r2-secret-key
R2_BUCKET=windy-cloud-storage
R2_ENDPOINT=https://{account_id}.r2.cloudflarestorage.com

# === Optional ===
# Database (defaults to SQLite for dev)
DATABASE_URL=sqlite+aiosqlite:///data/windy_cloud.db
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost/windy_cloud

# Compute - RunPod
RUNPOD_API_KEY=your-runpod-api-key
RUNPOD_ENDPOINT_ID=your-stt-endpoint-id
STT_MARKUP=3.0
STT_FREE_MINUTES=10

# Compute - AWS (Phase 2)
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
AWS_REGION=us-east-1
SAGEMAKER_ENDPOINT=windy-stt-endpoint

# VPS - AWS (Phase 3)
# Uses same AWS credentials as above
VPS_DEFAULT_REGION=us-east-1
VPS_DEFAULT_AMI=ami-ubuntu-24-04

# Server
HOST=0.0.0.0
PORT=8200
LOG_LEVEL=info
CORS_ORIGINS=https://windypro.thewindstorm.uk,https://cloud.windyfly.ai

# Quotas
DEFAULT_STORAGE_QUOTA=524288000  # 500MB in bytes
MAX_UPLOAD_SIZE=1073741824       # 1GB max per file
```

---

## DEPLOYMENT

### Target Infrastructure

- **VPS:** Hostinger at `72.60.118.54` (Ubuntu 24.04, Docker ready)
- **Port:** 8200 (fits the Windy port allocation scheme)
- **Domain:** `cloud.windyfly.ai` or `cloud.thewindstorm.uk`
- **Reverse proxy:** Nginx (same as other services)
- **SSL:** Let's Encrypt via certbot

### Port Allocation (Ecosystem)

| Service | Port |
|---------|------|
| Windy Pro Account Server | 3456 |
| Windy Chat | 8100-8104 |
| Windy Mail | 8025/8080 |
| Eternitas | 8300 |
| **Windy Cloud** | **8200** |

---

## RELATIONSHIP TO WINDY PRO'S EXISTING R2

Windy Pro's `account-server` currently has its own R2 adapter (`r2-adapter.ts`) storing recordings, transcriptions, and files in `windypro-storage` bucket.

**Migration path:**
1. **Phase 1:** Windy Cloud uses its own R2 bucket (`windy-cloud-storage`). Pro keeps its bucket.
2. **Phase 2:** Pro's file upload routes start writing to Cloud API instead of directly to R2.
3. **Phase 3:** Migrate existing Pro files from `windypro-storage` to `windy-cloud-storage`. Pro's R2 adapter becomes a thin proxy to Cloud.

This is **not urgent**. Both can coexist. Pro wrote to R2 first — Cloud unifies later.

---

## WHAT THE FRESH TERMINAL SHOULD BUILD FIRST

Priority order for implementation:

1. **`api/app/main.py`** — FastAPI app with CORS, lifespan, router includes
2. **`api/app/config.py`** — Pydantic settings from env vars
3. **`api/app/auth/jwks.py`** — Fetch JWKS from Pro, validate JWTs, extract identity
4. **`api/app/auth/dependencies.py`** — `get_current_user` FastAPI dependency
5. **`api/app/providers/r2.py`** — boto3 R2 adapter (port from Pro's TypeScript)
6. **`api/app/providers/local_disk.py`** — Local fallback for dev without R2
7. **`api/app/routes/storage.py`** — Upload, list, download, delete, usage
8. **`api/app/routes/archive.py`** — Product-specific archive endpoints
9. **`api/app/routes/health.py`** — Health check, status
10. **`api/app/db/`** — SQLAlchemy models + engine for metadata
11. **`Dockerfile`** + **`docker-compose.yml`** — Containerization
12. **Tests** — At least storage + auth tests

The compute (STT) and servers (VPS) pillars come in Phase 2-3.
