# SUBSTRATE — windy-cloud production

**ADR:** [ADR-048](https://github.com/sneakyfree/kit-army-config/blob/main/docs/adr-048-operational-substrate-as-code-2026-05-15.md) Layer 1
**Generated:** 2026-05-22 from `docker-compose.yml` (dev), `.github/workflows/deploy.yml`, `api/app/config.py`, `.env.example`, and lockbox cross-reference. Mostly inferred-from-repo-state — live `docker inspect` audit pending.
**Maintenance policy:** edit on every change to compose, host directory layout, or env vars. Drift detector (ADR-048 Layer 2, T2.A — not yet shipped) will eventually verify this against the live host nightly.
**Confidence flags:** ⓘ = inferred-from-repo-state without live verification. ⚠ = known gap or pending action.

---

## Host

| Field | Value |
|---|---|
| EC2 instance ID | `i-070327df339182f68` ⓘ (per memory `project_windy_cloud_persistence_substrate`) |
| Public IPv4 | `32.193.70.195` ⓘ (per same memory; matches deploy.yml comment) |
| SSH user | `ubuntu` (default per deploy workflow) |
| Repo path | `/opt/windy-cloud` (per deploy workflow `TARGET=/opt/windy-cloud`) |
| Compose dir | `/opt/windy-cloud` (root — compose files at top of TARGET) |

windy-cloud runs on its **own EC2** (NOT co-located with windy-mail/eternitas/windy-pro on `i-07cef803a6a3f86b4`). Separate isolation reflects the persistence-substrate criticality.

## Compose project

| Field | Value |
|---|---|
| Project name | `windy-cloud` ⓘ (inferred from container `windy-cloud-cloud-1` referenced in deploy verification step) |
| Compose file | `/opt/windy-cloud/docker-compose.prod.yml` ⚠ **NOT in git** — see Known Gaps below |
| Dev compose | `docker-compose.yml` (in git; used for local dev only, lacks the prod-shape: web + R2 + redis backends not present) |
| Env file | `/opt/windy-cloud/.env` (hand-curated, not in git; `.env.example` enumerates required keys) |

The compose project at the host level uses `name: windy-cloud` (inferable from the container-naming convention used by the deploy verification step). The committed `docker-compose.yml` does NOT declare a `name:` directive — that's tracked under T2.4 ADR-046 compose-naming audit gaps.

## Volumes — declared (dev compose) → on-host (inferred for prod)

The dev `docker-compose.yml` declares 2 volumes; the prod compose (not in git) likely adds more (Redis, web). What's confirmed:

| Compose name | On-host name (inferred) | Critical data | Notes |
|---|---|---|---|
| `cloud-data` | `windy-cloud_cloud-data` ⓘ | API app-state dir (`/app/data` inside container); SQLite fallback DB when DATABASE_URL unset | Re-buildable from R2 if R2 backend is configured |
| `postgres-data` | `windy-cloud_postgres-data` ⓘ | Postgres: user records, plans, audit log, server registry | **Top criticality — user persistence ledger** |

⚠ **Unknowns awaiting live audit:** Redis volume (if redis runs in compose vs ElastiCache), web container static assets, any R2-cache volume. The `.env.example` reference to `windy-cloud-cache.abc123.ng.0001.use1.cache.amazonaws.com` suggests prod uses ElastiCache, NOT a containerized redis — confirm on next audit.

## Bind mounts

Unknown — no bind mounts declared in the dev compose. Prod compose (not in git) may add bind mounts for:
- TLS certs (Let's Encrypt or imported)
- Nginx config (the repo has `deploy/nginx.conf`)
- R2-credentials file (alternative to env-injected secret)

To be filled on next live audit.

## Services (expected running)

The dev compose has `cloud`, `web`, `postgres`. The prod compose likely matches but with ElastiCache (Redis) attached + R2/RunPod credentials configured. Inferred service set:

| Compose service | Container name (inferred) | Image | Healthy when |
|---|---|---|---|
| cloud | `windy-cloud-cloud-1` ⓘ | (built from `./Dockerfile`) | `curl http://localhost:8200/health` and `/version` (MF1 — wired in PR #52) |
| web | `windy-cloud-web-1` ⓘ | (built from `./web/Dockerfile`) | `curl http://localhost:80` |
| postgres | `windy-cloud-postgres-1` ⓘ | `postgres:16-alpine` | `pg_isready -U windy -d windy_cloud` |

Possible additions in prod compose (NOT confirmed):
- caddy or nginx (TLS termination for `cloud.windycloud.com`)
- redis (or external ElastiCache)

## External ports (host-bound)

| Port | Service | Purpose |
|---|---|---|
| 8200 | cloud | API (per dev compose). In prod, likely bound to loopback + fronted by Caddy/nginx for TLS. ⓘ |
| 80 | web | Static web served on 80; likely Caddy/nginx proxies 443 → web. ⓘ |
| 443 | (TLS terminator) | `cloud.windycloud.com` per CORS_ORIGINS. ⓘ |

## Network

Unknown shape for prod. Dev compose has implicit default network. Prod may use a named external network if it shares with sister products on the box — but this EC2 is dedicated to windy-cloud so probably internal only.

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

⚠ **`docker-compose.prod.yml` is NOT committed to git.** The deploy workflow's `appleboy/scp-action` source list expects it at repo root (`source: "...,docker-compose.prod.yml"`). If it's missing on the EC2 too, every deploy will fail at the `docker compose -f docker-compose.prod.yml up` step. This is likely the unaddressed auto-deploy gap referenced in `[[feedback_mind_auto_deploy_unwired]]` memory ("Cloud and chat have similar gaps unaddressed"). Two possibilities:

  - (a) The prod compose has been hand-placed on the EC2 only — fine for dev but breaks reproducibility / cold-start recovery.
  - (b) The deploy workflow has been silently failing since PR #55 (2026-05-13). The `appleboy/scp-action` only copies the files in its source list; if `docker-compose.prod.yml` doesn't exist locally, the scp source-list resolution would 404 the file but might silently continue.

**Grant-on-return action:** SSH to `32.193.70.195`, capture `docker compose -f docker-compose.prod.yml config` output, commit a sanitized version (with env-var placeholders) to the repo root. Then update this manifest with the verified prod shape.

⚠ **Compose project name missing `name:` directive in committed compose.** Audit (T2.4) flagged `docker-compose.yml` as missing the explicit `name:` declaration. The prod compose likely has it (else the deploy verification step couldn't reference `windy-cloud-cloud-1` reliably) — confirm on next audit.

## Tolerated drift (allowlist)

Drift detector should NOT flag these. They are known pre-existing state that's non-load-bearing OR pending resolution:

| Item | Reason |
|---|---|
| Missing `name:` directive in `docker-compose.yml` | Dev compose; prod compose (not in git) has it implicitly. Track via T2.4. |
| `docker-compose.prod.yml` absent from repo | Known gap — see above. |
| Anonymous volumes on the `web` container | Static nginx assets — non-load-bearing. |
| `:abc123` or any unpinned image tag in prod compose | Pending capture-into-git of the prod compose; pin policy applies once committed. |

## Recovery — cold start from this manifest

If the EC2 is destroyed and rebuilt, recovery is **incomplete** without `docker-compose.prod.yml`. Steps that work today:

1. `git clone https://github.com/sneakyfree/windy-cloud /opt/windy-cloud`
2. Recover `docker-compose.prod.yml` from lockbox-backed EBS snapshot OR from a known-good EC2 SSH copy.
3. Restore `/opt/windy-cloud/.env` from lockbox (`ACCESS_LOCKBOX.md`).
4. Verify Postgres + R2 + RunPod credentials are still valid.
5. `cd /opt/windy-cloud && sudo docker compose --env-file .env -f docker-compose.prod.yml up -d`
6. Verify:
   - `curl https://cloud.windycloud.com/health` → `{"status":"healthy"}`
   - `curl https://cloud.windycloud.com/version` → MF1 metadata with deployed `commit_sha`
   - Identity webhook: simulate a `POST /api/v1/webhooks/identity/created` with valid HMAC; expect 200

Cold-start is **not currently reproducible from git-state alone** until the prod-compose gap is closed.

## Audit history

| Date | Trigger | Result |
|---|---|---|
| 2026-05-22 | Autonomous CTO loop T2.2 backfill | First substrate manifest authored from repo state. Discovered missing `docker-compose.prod.yml` gap (likely the auto-deploy gap memory referenced). Live audit pending. |

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
