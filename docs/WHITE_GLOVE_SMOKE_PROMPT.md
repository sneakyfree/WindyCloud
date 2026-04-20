# White-Glove Smoke Prompt — windy-cloud

**Created:** 2026-04-19, after Wave 13 Phase 3 deploy to AWS
**Purpose:** Hand to a fresh Claude session to do industrial-grade smoke testing on the deployed windy-cloud at `https://cloud.windyword.ai`.

---

## Why this prompt exists

Wave 13 Phase 3 shipped windy-cloud to AWS. It's the storage + billing + compute hub — R2 storage proxy, Stripe billing, sync, archive, deeplink, identity verification against Pro JWKS. None of this has been clicked through against the deployed surface yet. This prompt forces a fresh Claude session to behave like a paying customer + a cost-saboteur, hitting the real URL.

---

## Paste this to a fresh Claude session

> You are doing **industrial-grade white-glove smoke testing** on the production windy-cloud, freshly deployed to AWS as Wave 13 Phase 3 at `https://cloud.windyword.ai`. Your job is to find every defect a real paying user OR a cost-saboteur would hit. Unit tests do NOT count — only behaviour observed against the live URL counts.
>
> **Read first:**
>
> 1. `~/.claude/projects/-Users-thewindstorm/memory/MEMORY.md` (auto-loaded)
> 2. `/tmp/kit-army-config/ACCESS_LOCKBOX.md` — search for "Wave 13" and "windy-cloud"; gives you live URL `cloud.windyword.ai`, EC2 instance, RDS endpoint `windy-cloud-billing.cqxekagcetpz.us-east-1.rds.amazonaws.com`, Stripe sandbox keys, R2 credentials, IDENTITY_WEBHOOK_SECRET (Pro→Cloud).
> 3. `windy-cloud/api/app/main.py` — the router include table is the source of truth. 14 routers mounted: storage, archive, compute, billing, servers, sync, export, analytics, webhooks, stripe-webhook, identity, deeplink, agent-compat.
> 4. `windy-cloud/api/app/routes/` — each router's contract.
> 5. `windy-cloud/docs/WAVE13_PHASE3_RUNBOOK.md` — what Phase 3 actually shipped.
>
> **Then do all of the following against `https://cloud.windyword.ai`:**
>
> ### 1. Public surface
> - `GET /` and `GET /health` — both respond, latency under 200 ms? (Already confirmed 200 OK during Wave 13 deploy — re-verify and check response body).
> - `GET /docs` (FastAPI auto-docs) — should this be exposed in production? If yes, accessible. If no, must 404.
> - Send malformed JSON, wrong content-type, empty body, 10MB body — clean 400, never 500.
> - `GET /api/v1/<random-nonexistent>` → clean 404 envelope.
>
> ### 2. Identity verification — Pro JWKS contract
> - Fetch a real Pro-issued access token (use Pro's `/api/v1/oauth/device/code` flow against `pro.windyword.ai` or whatever the live URL is).
> - Hit any auth-required endpoint on cloud (e.g. `GET /api/v1/storage/files`) with that token. Verify cloud accepts it.
> - Hit it with a **forged** token (sign with a different key). Must 401.
> - Hit it with an **expired** token. Must 401.
> - Hit it with a **token signed by a key not in Pro's JWKS**. Must 401 (verify cloud actually fetched JWKS, doesn't just trust any signature).
>
> ### 3. Storage — R2 proxy
> - `POST /api/v1/storage/files/upload` with a small file (10 KB). Verify it lands in R2 (check the bucket via `aws s3 ls` or wrangler). Verify response has the correct file_id.
> - `GET /api/v1/storage/files/<id>` — does it return correct content? Correct mime type?
> - Upload a file **larger than the documented limit** (try 100 MB, 1 GB if the limit is high). Must reject cleanly with 413.
> - Upload a file as **user A**, try to fetch it as **user B** — must 403, no cross-tenant leak.
> - Delete a file. Verify it's gone from R2.
> - Try to delete someone else's file → 403.
>
> ### 4. Billing + Stripe webhook
> - `POST /api/v1/webhooks/stripe` — replay a real test-mode `checkout.session.completed` event with the right `Stripe-Signature` header (Stripe CLI: `stripe events resend <event_id>`). Verify cloud upgrades the user's tier.
> - Tampered signature → 400, no DB write.
> - `GET /api/v1/billing/subscription` for the user — does it reflect the new tier?
> - Trigger a `customer.subscription.deleted` — does cloud downgrade correctly?
> - Verify Stripe customer ID stays consistent across webhooks (no orphan customers).
>
> ### 5. Sync + archive + export
> - `POST /api/v1/sync/...` — exercise the chunked-recording upload path that windy-pro-mobile uses. Verify it round-trips.
> - `GET /api/v1/archive/...` — list, retrieve, restore.
> - `POST /api/v1/export/...` — request a data export. Does the job get queued? Does it complete? Where does the export land (R2)?
>
> ### 6. Compute + servers (if exposed)
> - `routes/compute` and `routes/servers` exist — probe what they expose. Spin up / list / tear down a compute resource if the API supports it. **WATCH OUT**: this is a cost-incurring path. Test with the smallest unit. Verify teardown actually tears down.
>
> ### 7. Deeplink + identity webhook receiver
> - `POST /api/v1/deeplink/...` — exercise the Wave 8 Grandma Ribbon hatch path. Pro fans `agent.hatched` to cloud's deeplink receiver. Sign with `IDENTITY_WEBHOOK_SECRET` (lockbox), POST a sample event, expect 200.
> - Tampered sig → 401. Missing sig → 401. Stale timestamp → 401.
>
> ### 8. Analytics + admin (if exposed)
> - `GET /api/v1/analytics/...` — what's exposed? Is it auth-gated? Does it return PII? **PII without admin role is a P0 bug.**
> - Any admin/operator UI — log in, click every nav, screenshot every page.
>
> ### 9. Agent-compat router
> - `agent_compat_router` is mounted at `/api/v1` with `include_in_schema=False` — that means it's a hidden surface for backwards-compat. Find what it exposes (read the source). Hit each endpoint. Should it still exist? Or is it deprecated cruft?
>
> ### 10. CORS, headers, TLS
> - OPTIONS from disallowed origin → no `*`.
> - HSTS, X-Content-Type-Options, X-Frame-Options, CSP all present.
> - SSL Labs grade ≥ A.
>
> ### 11. Cross-service contract verification
> - Confirm cloud actually fetches Pro's JWKS at `https://pro.windyword.ai/.well-known/jwks.json` (or wherever Pro hosts it) on startup and refreshes periodically. SSH the EC2 instance, tail logs.
> - Confirm Pro's identity webhook fanout is reaching cloud's webhook receiver — trigger a `user.created` on Pro, watch cloud's logs.
>
> ### 12. Production observability
> - Tail EC2 logs. ERROR/WARN must be explainable.
> - Postgres on RDS — connection pool healthy? Slow queries logged? Migration alembic head matches code?
>
> ---
>
> **Output format:** Single Markdown report at `windy-cloud/docs/SMOKE_REPORT_<YYYY-MM-DD>.md`. One H2 per section. Bug format: `**SEVERITY** — title — observed vs expected — repro — fix or "needs investigation"`. Severity: P0 = breaks billing / leaks PII / cross-tenant leak / accepts forged tokens, P1 = breaks a paid feature, P2 = ugly nonfatal, P3 = polish.
>
> **What "done" looks like:** zero P0, zero P1. 10-min readable report.
>
> **Constraints:**
> - Test the deployed URL.
> - **Cost discipline:** if you spin up compute/storage during test, tear it down. Document what you spun up.
> - Don't fix yet — discovery first.
> - Per branching policy (`windy-cloud/CLAUDE.md` if it exists, otherwise the ecosystem default): feature branch + PR. Admin merge if CI broken.
> - **2 OPEN Apr 17 hardening PRs** (#11 G6 Redis trust cache, #19 G14 passport-revoked replay) — DON'T touch; queued for Grant separately.
