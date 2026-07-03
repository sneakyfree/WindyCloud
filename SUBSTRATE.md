# SUBSTRATE — windy-cloud production

**ADR:** [ADR-048](https://github.com/sneakyfree/kit-army-config/blob/main/docs/adr-048-operational-substrate-as-code-2026-05-15.md) Layer 1
**Generated:** 2026-05-22 from `docker-compose.yml` (dev), `.github/workflows/deploy.yml`, `api/app/config.py`, `.env.example`, and lockbox cross-reference. Updated 2026-05-26 to reflect the committed `docker-compose.prod.yml` captured during the prod-compose-capture campaign — see Audit history.
**Maintenance policy:** edit on every change to compose, host directory layout, or env vars. Drift detector (ADR-048 Layer 2, T2.A — not yet shipped) will eventually verify this against the live host nightly.
**Confidence flags:** ⓘ = inferred-from-repo-state without live verification. ⚠ = known gap or pending action.

---

## ✅ Canonical domain status — `cloud.windycloud.com` is LIVE (resolved 2026-07-02)

The canonical host **`cloud.windycloud.com` now serves in production, globally.**
The earlier "windycloud cutover FAILED / NXDOMAIN" status is **resolved**. Root
cause was a stale DS record GoDaddy held at the `.com` registry, which made
validating resolvers SERVFAIL even though the A record in Cloudflare's zone was
correct. That stale DS was deleted on **2026-07-02** and the canonical host now
resolves + serves everywhere. The substrate also remains reachable on the legacy
`cloud.` host on the `windyword.ai` zone (dual-served, identical build).

**Only remaining item — operator-only, and NOT a Cloud blocker:** the
**registrar transfer** of `windycloud.com` from GoDaddy → Cloudflare. The
nameservers already point at Cloudflare (so serving works regardless of who
holds the registration), but `windycloud.com` is still registered at GoDaddy
under `clientTransferProhibited`. The 60-day transfer-lock window opens
**2026-07-21**; the operator-only fix sequence is GoDaddy unlock → obtain
EPP/auth code → initiate the Cloudflare registrar transfer → wait for approval.
Draft support messages are staged at `~/Desktop/windycloud-support-messages.md`.

**Implication for everything below:** recovery/verify steps that probe
`cloud.windycloud.com` now succeed. This is a registration-hygiene cleanup, not
a functional blocker — Cloud serving, auth, and every consumer work today.

---

## Host

| Field | Value |
|---|---|
| EC2 instance ID | `i-070327df339182f68` ✓ (verified in `docker-compose.prod.yml` header 2026-05-26) |
| Public IPv4 | `32.193.70.195` ✓ (verified in same compose header) |
| SSH user | `ubuntu` (default per deploy workflow) |
| Repo path | `/opt/windy-cloud` (per deploy workflow `TARGET=/opt/windy-cloud`) |
| Compose dir | `/opt/windy-cloud` (root — compose files at top of TARGET) |

windy-cloud runs on its **own EC2** (NOT co-located with windy-mail/eternitas/windy-pro on `i-07cef803a6a3f86b4`). Separate isolation reflects the persistence-substrate criticality.

## Compose project

| Field | Value |
|---|---|
| Project name | `windy-cloud` ✓ (per committed `docker-compose.prod.yml` `name:` directive; matches directory-derived default) |
| Compose file | `/opt/windy-cloud/docker-compose.prod.yml` ✓ **committed to git** as of 2026-05-26 (prod-compose-capture campaign closed the ADR-048 Layer 1 gap) |
| Dev compose | `docker-compose.yml` (in git; used for local dev only) |
| Env file | `/opt/windy-cloud/.env` (hand-curated, not in git; `.env.production.example` enumerates required keys) |

## Volumes — declared (prod compose)

The committed `docker-compose.prod.yml` declares ZERO named volumes — Wave 13 Phase 3 moved persistence off the box:

- **Postgres**: replaced by AWS RDS (no `postgres-data` volume in prod compose)
- **Redis**: replaced by AWS ElastiCache (no redis container in prod compose)
- **App-state**: handled via R2 / RDS (no `cloud-data` volume needed in prod compose)

⚠ **NOTE:** The earlier SUBSTRATE.md inferred `cloud-data` + `postgres-data` from the dev compose; the committed prod compose contradicts this. The dev compose is dev-only convenience — durable prod state is external (RDS + ElastiCache + R2).

## Bind mounts

Unknown — no bind mounts declared in the dev compose. Prod compose (not in git) may add bind mounts for:
- TLS certs (Let's Encrypt or imported)
- Nginx config (the repo has `deploy/nginx.conf`)
- R2-credentials file (alternative to env-injected secret)

To be filled on next live audit.

## Services (running in prod)

The committed `docker-compose.prod.yml` declares a **single service** (Wave 13 Phase 3 simplification — postgres/web removed, RDS+ElastiCache handle their roles):

| Compose service | Container name | Image | Healthy when |
|---|---|---|---|
| cloud | `windy-cloud-cloud-1` ✓ | (built from repo `./Dockerfile`) | `curl http://localhost:8200/health` and `/version` (MF1) |

Host-level TLS termination is via system nginx (not in compose) per the compose header note: "host nginx reverse-proxies from 443".

## External ports (host-bound)

| Port | Service | Purpose |
|---|---|---|
| `127.0.0.1:8200->8200` | cloud (host 8200 → container 8200) ✓ | API loopback; host nginx terminates TLS for `cloud.windycloud.com` and proxies to 8200. |

## Network

Implicit default network (committed prod compose declares no networks block) — single-service stack, no inter-container traffic. Dedicated EC2 (`i-070327df339182f68`), not co-located with other Windy services.

## External backends (optional, env-toggled)

| Backend | Trigger env vars | Purpose |
|---|---|---|
| Cloudflare R2 | `R2_ACCOUNT_ID` + `R2_ACCESS_KEY_ID` + `R2_SECRET_ACCESS_KEY` + `R2_BUCKET` (all four together) | Object storage; falls back to local-disk when unset |
| RunPod | (separate env vars; see `api/app/providers/runpod.py`) | On-demand GPU compute for clone training, voice gen |
| ElastiCache (Redis) | `REDIS_URL` | Shared cache + dedup for horizontally-scaled workers |
| AWS Secrets Manager | (configured in deploy/docs/env-vars.md) | Source of truth for shared secrets in prod |

## Critical env vars (must be present in /opt/windy-cloud/.env)

**Required for boot:**
- `POSTGRES_PASSWORD` (compose default `windycloud` is dev-only)
- `DATABASE_URL` (otherwise falls back to SQLite — not safe for prod)

**Required for identity + webhooks:**
- `WINDY_PRO_JWKS_URL` (default `https://windyword.ai/.well-known/jwks.json`)
- `ETERNITAS_JWKS_URL` (default `https://api.eternitas.ai/.well-known/eternitas-keys`)
- `IDENTITY_WEBHOOK_SECRET` (shared with windy-pro)
- `ETERNITAS_WEBHOOK_SECRET`

**Required for Stripe:**
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`

**Required for service-to-service:**
- `CHAT_PUSH_GATEWAY_URL`

**Required for admin gating (Wave 14):**
- `ADMIN_IDENTITY_IDS` (comma-separated list of windy_identity_ids permitted on `/api/v1/analytics/*` and similar fleet-wide routes)

**MF1 deploy-identity (set by deploy workflow at build time):**
- `COMMIT_SHA`
- `BUILD_TIMESTAMP`
- `ENVIRONMENT=production`

Per `[[feedback_pydantic_settings_list_env]]`: `CORS_ORIGINS` must be JSON-quoted in `.env` files for pydantic-settings list parsing — comma-separated forms crash boot.

## Known gaps + audit findings

✓ **`docker-compose.prod.yml` is committed to git** as of 2026-05-26 (prod-compose-capture campaign). Cold-start is now reproducible from git-state alone (modulo `.env` + RDS/ElastiCache external state).

✓ **Project name `name: windy-cloud`** verified in committed prod compose.

✓ **Wave 13 Phase 3 dev/prod compose divergence is now self-documenting**: the committed prod compose is a single-service stack (no postgres, no web, no redis) — RDS+ElastiCache+system-nginx replaced the local containers. The dev compose keeps the 3-container shape so local dev is self-contained. As of 2026-06-06 `docker-compose.yml` carries a header comment explaining the divergence is intentional and pointing back to this SUBSTRATE.md; the earlier "warrants a future doc reconciliation" note is resolved.

## Tolerated drift (allowlist)

Drift detector should NOT flag these. They are known pre-existing state that's non-load-bearing OR pending resolution:

| Item | Reason |
|---|---|
| Missing `name:` directive in `docker-compose.yml` (dev) | Dev compose; prod compose has explicit `name: windy-cloud`. Track via T2.4 for the dev side. |
| Dev compose has postgres+web services not present in prod | Wave 13 Phase 3 simplification — prod uses RDS + system nginx instead. Dev/prod divergence is intentional. |

## Recovery — cold start from this manifest

Reproducible from git-state alone (with lockbox-restored `.env` and valid RDS + ElastiCache + R2 + RunPod credentials):

1. `git clone https://github.com/sneakyfree/windy-cloud /opt/windy-cloud`
2. Restore `/opt/windy-cloud/.env` from lockbox (`ACCESS_LOCKBOX.md`).
3. Verify RDS + R2 + RunPod credentials are still valid.
4. `cd /opt/windy-cloud && sudo docker compose --env-file .env -f docker-compose.prod.yml up -d`
5. Restore/configure host nginx for TLS termination (proxy 443 → 127.0.0.1:8200).
6. Verify (see the **Canonical domain status** callout at the top — until the
   GoDaddy→Cloudflare registrar transfer completes, `cloud.windycloud.com`
   returns NXDOMAIN and you must probe the legacy `cloud.` host on the old
   `windyword.ai` zone instead; a failing curl here is a DNS/registrar
   state, NOT a deploy bug):
   - `curl https://cloud.windycloud.com/health` → `{"status":"healthy"}`
   - `curl https://cloud.windycloud.com/version` → MF1 metadata with deployed `commit_sha`
   - Identity webhook: simulate a `POST /api/v1/webhooks/identity/created` with valid HMAC; expect 200

## Audit history

| Date | Trigger | Result |
|---|---|---|
| 2026-05-22 | Autonomous CTO loop T2.2 backfill | First substrate manifest authored from repo state. Discovered missing `docker-compose.prod.yml` gap (likely the auto-deploy gap memory referenced). Live audit pending. |
| 2026-05-26 | Prod-compose-capture campaign (5 parallel SSH-verified captures) | `docker-compose.prod.yml` committed to git. Promoted ⓘ→✓ on EC2 ID + IP (now in compose header), project name `windy-cloud`, container name `windy-cloud-cloud-1`, port binding `127.0.0.1:8200:8200`. **Surfaced Wave 13 Phase 3 simplification**: prod compose is single-service (no postgres/web/redis containers — RDS+ElastiCache+system-nginx replaced them). SUBSTRATE.md updated to reflect prod-true shape; dev compose still has 3-container shape (intentional divergence). |
| 2026-06-06 | Doc-reconciliation maintenance pass | Added the **Canonical domain status** callout making it unambiguous that the "windycloud cutover FAILED" item is an operator-only GoDaddy→Cloudflare registrar transfer (Grant-only), NOT a code/deploy bug, and annotated the recovery curl steps accordingly (NXDOMAIN on `cloud.windycloud.com` is expected pre-transfer). Documented the intentional dev/prod compose divergence with a header comment in `docker-compose.yml`; resolved the prior "warrants a future doc reconciliation" note. |

## Cross-references

- ADR-048: `kit-army-config/docs/adr-048-operational-substrate-as-code-2026-05-15.md`
- ADR-028: `kit-army-config/docs/adr-028-cloud-persistence-substrate-2026-05-12.md`
- windy-mail SUBSTRATE.md (reference impl): `/Users/thewindstorm/windy-mail/deploy/SUBSTRATE.md`
- Migration runbook: `kit-army-config/docs/deploy-prod-collision-migration-runbook-2026-05-15.md`
- Memory: `project_windy_cloud_persistence_substrate.md` (EC2 ID + IP source)
- Memory: `feedback_mind_auto_deploy_unwired.md` (notes that Cloud has similar unaddressed gap)
- Memory: `feedback_caddy_inode_binding_v2.md` (if Caddy is on this box — pending audit)
- Memory: `feedback_pydantic_settings_list_env.md` (CORS_ORIGINS JSON-format trap)
- Memory: `reference_lockbox.md`
- PR #52 — `/version` endpoint (MF1)
- PR #55 — Deploy workflow rewrite (where the prod-compose gap was introduced/exposed)
