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

## Branching Policy

Feature branches + PR review across every Windy repo. Do **not** push
directly to `main`; open a PR and let Grant merge it. See
`~/.claude/memory/feedback_branching_policy.md` for the full rule.

### Wave 7 batch-only exception (2026-04-17)

For the Wave 7 PR batch-merge only, Grant granted a one-time exception
allowing Claude to self-merge **Bucket A** PRs (per
`docs/MERGE_TRIAGE.md`) via
`gh pr merge <num> --squash --delete-branch --admin` with a smoke test
between each merge. Bucket B still self-merged but only after the full
integration suite passes post-merge; on regression, stop and revert.
Bucket C and beyond stay PR-only, reviewer-required.

Scope: this exception applies *only* to the PRs open as of
`docs/MERGE_TRIAGE.md` at commit 989ea6d. After Wave 7 closes, the
standard branch-PR-review policy resumes with no further Claude
self-merges.

## Windy Admin telemetry (stress-test contract) — 2026-07-07

**There is ONE super-admin dashboard for the whole ecosystem at
`https://admin.windyword.ai`** (repo `sneakyfree/windy-admin`, ADR-WA-001).
Every platform PUSHES small content-free JSON events to its central ingest;
the dashboard reads them (Fleet / Members / Agents / Cost / Experiment /
Audit). **When you stress-test this platform, it is part of the job to prove
its activity shows up on that dashboard.** Missing telemetry is a GAP to
close, exactly like a bug — and each platform verifying its own telemetry in
parallel doubles as a load test of the panel.

**This repo:** NOT WIRED — should emit storage-provisioned + quota-consumption events. Token `…__WINDY_CLOUD` is pre-minted and live in the ingest map — instrument during your stress test and verify it lands.

**Verify during your stress test** (read token `verify-oc5` in lockbox
`secrets/windy-admin/ingest-tokens.env`):
```bash
curl -s "https://admin.windyword.ai/v1/events/tail?limit=10&platform=windy-cloud" \
  -H "Authorization: Bearer <verify-oc5>" | python3 -m json.tool
```
Drive real traffic, then confirm your events appear here AND on the dashboard
page they feed. If they don't, fix the emitter (or the aggregation query).

**Hard rules (non-negotiable):**
- **Fire-and-forget**: post async, short timeout, swallow every error. A dead
  ingest must NEVER break this product (proven: chat runs fine with the ingest
  down).
- **Inert unless configured**: no-op when `WINDY_ADMIN_INGEST_URL` /
  `WINDY_ADMIN_INGEST_TOKEN` are unset.
- **Privacy hard line**: counts / costs / durations / models / ids only. Cost
  is INTEGER microcents (10^-6 USD). The ingest 422s any metadata key whose
  camelCase/snake tokens match content/text/body/message/prompt/transcript/
  subject/html/completion/reply — if you get 422'd, FIX THE EVENT, never ask
  for the guard to be loosened.

**Full brief + per-platform table + how-to-instrument:**
`~/kit-army-config/docs/windy-admin-telemetry-campaign-2026-07-07.md`.

## CI: self-hosted runner (since 2026-07)
GitHub Actions runs on OUR runner (kit0-WindyCloud on the Kit 0 VPS), not GitHub's cloud.
Always `runs-on: [self-hosted, linux, x64]` — NEVER `ubuntu-latest` (billing-locked; runner-lint enforces).
Jobs stuck "Queued" = runner down, not billing: ssh Kit 0 → cd /home/github-runner/runners/WindyCloud && sudo ./svc.sh status
Full runbook: ~/kit-army-config/docs/ci-runner-runbook.md
