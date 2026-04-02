# Windy Cloud

**Your digital life, unified — one cloud for storage, compute, and servers across the entire Windy ecosystem.**

**Repo:** [github.com/sneakyfree/WindyCloud](https://github.com/sneakyfree/WindyCloud)

---

## The Problem

Every Windy product stores data separately — recordings in Pro, messages in Chat, emails in Mail, memories in Fly. There's no central place to browse, back up, or restore your data. And when your laptop is on fire, local voice-to-text crawls.

## The Solution

Windy Cloud is the **iCloud of the Windy ecosystem**. Three pillars:

1. **Storage** — Cold storage for all products. Archive chat backups, mail exports, agent memories, recordings. Browse from a web portal.
2. **Compute** — Cloud GPU for speech-to-text. Pay per minute, way faster than local. Start on AWS/RunPod, grow into own GPU cluster.
3. **Servers** — VPS hosting on AWS. Provision cloud servers through the Windy platform.

## Architecture

Hub-and-spoke: each product keeps hot storage locally, archives to Cloud for long-term cold storage.

```
Windy Pro ──┐
Windy Chat ─┤
Windy Mail ─┼──► Windy Cloud (R2 + AWS GPU + AWS EC2)
Windy Fly ──┤
Windy Code ─┘
```

Auth via Windy Pro's JWKS — no separate Cloud login.

## Quick Start

```bash
# 1. Clone
git clone https://github.com/sneakyfree/WindyCloud.git windy-cloud
cd windy-cloud

# 2. Install
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env  # edit with your R2 + auth values

# 4. Start
uvicorn api.app.main:app --reload --port 8200

# 5. Verify
# http://localhost:8200/health
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Framework | FastAPI (Python) |
| Storage | Cloudflare R2 (boto3) |
| GPU Compute | RunPod Serverless / AWS SageMaker |
| VPS | AWS EC2 |
| Auth | RS256 JWT via Windy Pro JWKS |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Container | Docker |

## Part of the Windy Ecosystem

| Product | Role |
|---------|------|
| **Windy Pro** (Windy Word) | Identity hub, auth authority |
| **Windy Chat** | Matrix-based messaging |
| **Windy Mail** | Email for humans and agents |
| **Windy Fly** | AI agent platform |
| **Windy Code** | AI-native IDE |
| **Windy Mobile** | React Native companion |
| **Windy Cloud** | **This repo** — unified cloud platform |
| **Eternitas** | Bot identity & verification |

## Key Documents

- [DNA_STRAND_MASTER_PLAN.md](DNA_STRAND_MASTER_PLAN.md) — Complete architecture blueprint
- [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) — Per-product integration docs

## Status

**Phase:** 0 — Skeleton + DNA Strand
**Port:** 8200
**Domain:** cloud.windyfly.ai (planned)
