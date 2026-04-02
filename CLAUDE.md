# Windy Cloud — Claude Code Instructions

## What This Is

Windy Cloud is the unified cloud platform for the Windy ecosystem (8 products). Three pillars: Storage (R2), Compute (GPU STT), Servers (VPS). Think iCloud for all Windy products.

## Read First

1. `DNA_STRAND_MASTER_PLAN.md` — Complete architecture, decisions, API design, file index
2. `INTEGRATION_GUIDE.md` — How each product connects to Cloud
3. `README.md` — Quick overview

## Tech Stack

- Python 3.11+ / FastAPI / Uvicorn
- boto3 for Cloudflare R2 (S3-compatible)
- PyJWT for RS256 JWKS validation
- SQLAlchemy async for metadata DB
- Docker for deployment

## Build Priority

Follow the "What the Fresh Terminal Should Build First" section in DNA_STRAND_MASTER_PLAN.md.

## Key Conventions

- Port 8200
- Auth via Windy Pro JWKS (no separate user DB)
- File paths: `{windy_identity_id}/{product}/{type}/{filename}`
- Providers are swappable (interface pattern)
- Agent-friendly: simple REST, clear errors, no CAPTCHAs

## Part of the Windy Ecosystem

- Windy Pro (account-server): identity authority, JWKS at `/.well-known/jwks.json`
- Eternitas: bot identity, JWKS at `/.well-known/eternitas-keys`
- All repos: github.com/sneakyfree/
- VPS: 72.60.118.54 (Hostinger, Ubuntu 24.04, Docker)

## Owner

Grant Whitmer — founder of the Windy ecosystem. Prefers Python-first, normie-friendly UX, agent-first design.
