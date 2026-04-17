# GAP ANALYSIS — what's actually broken before launch

*Wave 7 adversarial audit.* 2026-04-16.
Not polite. Not defensive. Everything I could find wrong tonight.

> **Rules of engagement.** "Tests pass" ≠ "service works." The offline
> suite shows 142/142 green, but that only proves the code does what the
> *tests* say. Real users break services in ways tests don't. Below is
> what I found by stepping outside the test harness: live probes, git
> audits, running the app with adversarial inputs, and reading the code
> with the attacker's eyes.

---

## TOP 5 THINGS THAT WILL SURPRISE GRANT MOST

1. **Frozen / revoked users can still read, list, export, and delete their
   data.** The freeze gate I shipped only blocks `POST /storage/upload`
   and the `POST /archive/{product}` endpoints. Revoked users can still
   call `GET /storage/files`, `GET /files/{id}`, `GET /storage/export`
   (ZIP of all files), `GET /archive/retrieve/...`, and
   `DELETE /storage/files/{id}`. Reproduced live — a frozen user lists
   their files, downloads the ZIP, wipes their own data. **G1, P0.**

2. **`.env.example` is missing every shared secret Wave 2/3/4 introduced.**
   Zero entries for `IDENTITY_WEBHOOK_SECRET`, `SERVICE_TOKEN`,
   `ETERNITAS_WEBHOOK_SECRET`, `ETERNITAS_URL`, `ETERNITAS_USE_MOCK`, any
   `TIER_QUOTA_*`, `SENTRY_DSN`, or `TRUST_*`. A new dev cloning the repo
   and copying `.env.example` ships with the webhooks 503-ing (`secret
   not configured`), the trust client hitting the default
   `http://localhost:8500`, and billing allocate accepting requests with
   `service_token=""` being the only thing the secret has to match.
   **G5, P0.**

3. **The JWT validator doesn't verify `iss` or `aud` — any token signed
   by Pro's or Eternitas's key gets in, regardless of intended audience.**
   `auth/jwks.py:39` sets `options={"require": ["exp", "sub"]}` and
   calls `jwt.decode()` with no `audience=` argument. If either hub ever
   mints a non-Cloud token (ID token, internal service token, anything),
   that token silently authenticates to Cloud. **G8, P0.**

4. **`data = await file.read()` runs *before* the `max_upload_size` check
   on every upload path.** A 1 GB request buffers 1 GB of Python bytes
   on a 1 GB Fargate task before returning 413. Under any real traffic
   this is OOM. Live probe confirms: FastAPI swallows the whole body
   before the handler gets a chance to reject. **G2, P0.**

5. **`init_db()` runs `Base.metadata.create_all()` on every startup,
   racing Alembic.** `db/engine.py:17`. Production uses Alembic as the
   schema authority (`deploy/aws/CLOUD_DEPLOYMENT.md` §4.3). A fresh pod
   that starts before the migration task finishes will silently create
   tables at the *current model schema* without stamping alembic's
   `version` table — the next `alembic upgrade head` errors with "table
   already exists" and the cluster pins to whatever schema the first
   pod imagined. **G10, P0.**

---

## Severity counts

| Severity | Count |
|---|---|
| **P0** (ship-blocker) | 10 |
| **P1** (fix this week) | 14 |
| **P2** (polish) | 9 |
| **P3** (nice-to-have) | 6 |

---

## P0 — SHIP-BLOCKERS

### G1. Freeze is upload-only; revoked users keep read/list/export/delete access
- **What's broken.** Only `POST /storage/upload` and `POST /archive/*`
  gate on `UserPlan.frozen`. A frozen user retains full access to
  `GET /storage/files` (list), `GET /files/{id}` (download),
  `GET /storage/export` (ZIP all), `GET /archive/retrieve/{product}/{filename}`,
  `DELETE /files/{id}`, and `POST /archive/migrate`.
- **Repro.** Live test in this session:
  ```python
  # Seed a UserPlan(frozen=True) + one FileRecord for 'frozen-user'
  # GET /api/v1/storage/files → 200 with the file listed
  # GET /api/v1/storage/export → 200 (ZIP streams)
  # POST /api/v1/storage/upload → 403 frozen_account ✓ (upload correctly blocked)
  ```
- **Fix.** Swap `Depends(get_current_user)` for `Depends(require_not_frozen)`
  (or the new `require_not_blocked`) on every mutating AND non-public read
  route in `routes/storage.py` + `routes/archive.py`. Same treatment for
  `routes/export.py` and the `/api/v1/{files,usage,export,breakdown,upload}`
  agent-compat mirrors.
- **File:line.** `api/app/routes/storage.py:60,141,191,229,253,327,348`;
  `api/app/routes/archive.py:216,226,311`; `api/app/routes/export.py:94`.
- **Effort.** ~1h code + tests per route group.

### G2. Unbounded `await file.read()` before the size check
- **What's broken.** `storage.py:81`, `archive.py:118`, `compute.py:106`
  all do `data = await file.read()` and *then* compare `len(data) >
  max_upload_size`. FastAPI's UploadFile spools >1 MB to disk, but the
  `data = await file.read()` call materialises the whole thing into a
  Python `bytes`. `max_upload_size` default is 1 GB; Fargate task memory
  in the deploy doc is 1024 MB. One concurrent 1 GB upload = OOM kill.
- **Repro.** Fire a 500 MB POST to `/api/v1/storage/upload` with a
  valid bearer — watch the worker's RSS climb to ~1 GB before the
  handler's size check fires.
- **Fix.** Either (a) read in chunks and short-circuit when the running
  total exceeds `max_upload_size`, or (b) reject via the ASGI request's
  `Content-Length` header before touching the body, or (c) set ALB /
  nginx `client_max_body_size` to a sane per-tier limit and trust the
  edge. (c) is the cheapest deploy-side mitigation.
- **File:line.** `api/app/routes/storage.py:80-85`,
  `archive.py:117-122`, `compute.py:105-110`.
- **Effort.** 2-3h (implement chunked size check + tests).

### G3. `max_upload_size=1 GB` ≥ Fargate task memory (1024 MB)
- **What's broken.** `config.py:54` + deploy doc §5.2 task sizing (1024
  MB memory) — a single legitimate max-sized upload pushes the pod into
  OOM.
- **Fix.** Drop default to `min(256 MB, tier_quota_per_file)`. Publish a
  per-tier max-upload ceiling, enforce at ALB WAF too.
- **File:line.** `api/app/config.py:54`, `deploy/aws/CLOUD_DEPLOYMENT.md:§5.2`.
- **Effort.** 15m + coordinate with WAF rule.

### G4. `R2_BUCKET` default mismatches production name
- **What's broken.** `config.py:22` ships `r2_bucket = "windy-cloud-storage"`
  but `deploy/aws/CLOUD_DEPLOYMENT.md:§3.1` and the Secrets Manager seed
  names `windy-cloud-storage-prod`. First prod deploy without
  `R2_BUCKET` explicitly set will hit a non-existent bucket and the S3
  provider will 404 every upload.
- **Repro.** Start the app with R2 creds but no `R2_BUCKET` → storage
  health reports `ok` (optimistic) until the first upload 502s.
- **Fix.** Either ship the default as `""` and fail fast at startup when
  unset, or use `-${ENV}` suffix in Secrets Manager and read that.
- **File:line.** `api/app/config.py:22`.
- **Effort.** 10m.

### G5. `.env.example` is missing every post-Wave-1 env var
- **What's broken.** 22 config fields defined on `Settings` are not in
  `.env.example`. Critical ones: `IDENTITY_WEBHOOK_SECRET`,
  `SERVICE_TOKEN`, `ETERNITAS_WEBHOOK_SECRET`, `ETERNITAS_URL`,
  `ETERNITAS_USE_MOCK`, `TIER_QUOTA_FREE|PRO|ULTRA|MAX`, `SENTRY_DSN`,
  `AWS_*`, `RUNPOD_*`, `SAGEMAKER_*`. A dev copying the example ships
  a prod-broken config. The CLOUD_DEPLOYMENT.md checklist (§9) doesn't
  catch this because it references `/prod/windy-cloud/shared` directly.
- **Repro.** `cp .env.example .env && uvicorn api.app.main:app`
  → `POST /webhooks/identity/created` returns 503 `Webhook secret not
  configured` because `IDENTITY_WEBHOOK_SECRET` never got set.
- **Fix.** Regenerate `.env.example` from `Settings.__fields__`. Add a
  unit test that fails if `.env.example` lacks a field declared on
  `Settings`.
- **File:line.** `.env.example` (full file); test at
  `api/tests/test_config_env_example.py` (new).
- **Effort.** 30m.

### G6. Authorised Fargate workers don't share state — trust cache, dedup set, upload semaphore are per-worker
- **What's broken.** Three separate per-process state bags that the
  design assumes are global:
  - `services/trust_client.py:116` — `self._cache` dict. Each Fargate
    task has its own view. A `trust.changed` webhook lands on exactly
    one task → only that task's cache is flushed; the rest keep
    returning stale trust until their 5-min TTL rolls over. Revocations
    visible to one worker, not the others.
  - `routes/webhooks.py:237` — `_seen_deliveries` set. Idempotency
    claim ("dedupe on `X-Eternitas-Delivery`") holds only within a
    single worker. N tasks = up to N duplicate processings of the same
    retry. For trust.changed this is idempotent (cache-invalidate is
    idempotent), but for passport/revoked it's `UserPlan.frozen=True`
    twice — benign — *until* we add side effects.
  - `routes/archive.py:32` — `_upload_semaphore = asyncio.Semaphore(5)`.
    Documented "concurrency limit 5" is actually `5 × N_tasks`.
- **Fix.** Move cache + dedup to Redis (already prescribed in
  `CLOUD_DEPLOYMENT.md` for session state). Upload semaphore: move to
  an in-pod ulimit / delete entirely and rely on Fargate's ephemeral
  disk for spool.
- **File:line.** see above.
- **Effort.** ~1d (introduce a Redis client, migrate three call sites,
  tests).

### G7. JWT validator doesn't verify `aud` / `iss`; cross-product tokens accepted
- **What's broken.** `auth/jwks.py:34-40`. `jwt.decode(...)` runs with
  `options={"require": ["exp", "sub"]}` and no `audience=` / `issuer=`.
  A token minted by Windy Pro's account-server for **any** downstream
  product — Mail, Chat, Code, a future service — authenticates to
  Cloud because the signing key is the same JWKS. Same with Eternitas
  EPT tokens for bots.
- **Fix.** Add `audience="windy-cloud"` (or whatever we agree on in the
  cross-product contract) and `issuer=settings.windy_pro_issuer` to
  `jwt.decode`. Coordinate `aud` value with windy-pro.
- **File:line.** `api/app/auth/jwks.py:34-40`.
- **Effort.** 1h + cross-repo coordination.

### G8. Trust gate fails OPEN on Eternitas network error
- **What's broken.** `services/trust_client.py:138-151` — any
  `httpx.HTTPError`, timeout, or 5xx returns `None`, and
  `auth/webhook.py:_raise_if_blocked` treats `None` as "skip trust
  check, let the request through." DoSing Eternitas for 5 minutes
  bypasses every suspended/revoked gate.
- **Fix.** Fail-closed for mutations: a `None` trust result on a path
  with a linked passport should 503 with `trust_unavailable`. Keep
  fail-open only for listing/read paths. Alternatively, cache the last
  *successful* `status` for longer than the normal TTL and rely on it
  during outages.
- **File:line.** `api/app/services/trust_client.py:138-151`,
  `api/app/auth/webhook.py:85`.
- **Effort.** 2h.

### G9. `/docs`, `/redoc`, `/openapi.json` served publicly in prod
- **What's broken.** Live probe against the running server:
  `GET /docs → 200`, `GET /openapi.json → 200`, no auth. Exposes the
  full API surface including service-token endpoints, internal webhooks,
  and the identity-bridge resolver.
- **Fix.** In `api/app/main.py:create_app`, pass `openapi_url=None,
  docs_url=None, redoc_url=None` when `settings.dev_mode` is False.
- **File:line.** `api/app/main.py:71-77`.
- **Effort.** 15m.

### G10. `init_db()` race with Alembic
- **What's broken.** `db/engine.py:17` runs `Base.metadata.create_all`
  on every app startup. In production that competes with the
  `alembic upgrade head` one-shot task prescribed in CLOUD_DEPLOYMENT.md.
  If an API task starts first, it creates tables at the current model
  schema *without* writing to `alembic_version`; the subsequent
  migration task fails on the first `op.create_table(...)` with
  "table already exists".
- **Fix.** Gate the `create_all` call on `settings.dev_mode` OR on a
  `WINDY_CLOUD_SCHEMA_BOOTSTRAP=true` env var. Production path: only
  Alembic writes schema.
- **File:line.** `api/app/db/engine.py:13-18`; `api/app/main.py:60-63`.
- **Effort.** 30m.

---

## P1 — FIX THIS WEEK

### G11. Auth + money code below the 80% coverage bar
`pytest --cov` run against `api/app`:

| File | Coverage | Classification | Severity |
|---|---|---|---|
| `auth/jwks.py` | **43%** | auth | P1 — failing the P0 gate in Grant's prompt, but G7 above already captures the worst-case |
| `auth/webhook.py` | **43%** | auth + frozen | P1 |
| `auth/dependencies.py` | **47%** | auth | P1 |
| `routes/billing.py` | **54%** | money | P1 — `_estimate_storage_cost`, `billing_sync`, `upgrade_plan` untested |
| `services/trust_client.py` | **67%** | identity | P1 — error paths uncovered (G8) |
| `providers/r2.py` | **0%** | storage | P1 — the primary blob store has zero tests |
| `providers/aws_ec2.py` / `runpod.py` / `sagemaker.py` | **0%** | infra | P2 — provider shells |

Full per-file breakdown in `docs/audit/coverage-gaps.md`. Shipping without
at least 80% on the auth / billing / trust files is irresponsible given
how many of the P0s above live in that untested code.

### G12. Concurrent `link-passport` for the same identity: 4 of 5 parallel calls 500
- **What's broken.** Live probe — 5 parallel POSTs to
  `/api/v1/identity/link-passport` with the same `windy_identity_id`
  and 5 different `passport_number`s returned `200, 500, 500, 500, 500`.
  Root cause: `routes/webhooks.py:_link_passport` does a SELECT → branch
  → INSERT path with no `ON CONFLICT` / advisory lock. SQLAlchemy raises
  IntegrityError → 500.
- **Fix.** Use `INSERT ... ON CONFLICT (windy_identity_id) DO UPDATE` via
  `sqlalchemy.dialects.postgresql.insert` on Postgres, or
  `sqlite.insert().on_conflict_do_update` for dev. Or wrap in a retry
  loop.
- **File:line.** `api/app/routes/webhooks.py:_link_passport` (~line 363).
- **Effort.** 1h.

### G13. `archive_migrate` still requires user JWT, inconsistent with the rest of `/archive/*`
- **What's broken.** Wave 2 swapped the five upload endpoints to
  `get_user_or_service` so product backends could service-auth with a
  `windy_identity_id` form field. `archive_migrate` (`routes/archive.py:226`)
  was missed and still hard-requires `get_current_user`. Product
  backends (mail/chat/clone/agent) cannot batch-register migrations
  without impersonating a user JWT.
- **Fix.** Swap the dependency; add `windy_identity_id` to
  `MigrateRequest` so service callers can specify the target identity
  instead of reading it from the JWT.
- **File:line.** `api/app/routes/archive.py:226-230`.
- **Effort.** 30m.

### G14. Passport-revoked webhook has no timestamp / nonce replay protection
- **What's broken.** `routes/webhooks.py:handle_passport_revoked`
  validates the ES256 token against the Eternitas JWKS but nothing
  anti-replay. An attacker who observes one revocation token can POST
  it again later. `UserPlan.frozen = True` is idempotent so the damage
  is cosmetic (logs + metrics), but as soon as we add any side effect
  (notification, audit entry, SOX/GDPR record-of-processing) replay is
  exploitable.
- **Fix.** Require `exp` / `jti` in the token, cache seen JTIs in Redis
  (dedupe window = `exp`). Reject unsigned outer body too.
- **File:line.** `api/app/routes/webhooks.py:140-202`.
- **Effort.** 2h (after Redis lands).

### G15. `identity/created` webhook has the same replay gap + a header-name collision
- **What's broken.** Same story as G14 — no timestamp check, no
  dedupe. Plus, I signed it with `X-Windy-Signature` (HMAC) while
  Eternitas's `docs/webhooks.md` defines `X-Windy-Signature` as the
  ecosystem-wide detached-ES256-JWS header. If Windy Pro ever adopts
  Eternitas's ecosystem signing, Cloud will interpret JWS-signed bodies
  as HMAC-signed → every webhook 403s.
- **Fix.** Rename header to `X-Windy-Identity-Signature` (or use
  `X-Pro-Signature` per whichever repo is the signer). Add timestamp +
  dedupe same as G14.
- **File:line.** `api/app/auth/webhook.py:49-56`,
  `api/app/routes/webhooks.py:54-70`.
- **Effort.** 1h.

### G16. `storage_router` double-mounted; agent-compat mirrors don't have the frozen check
- **What's broken.** `main.py:119` mounts `storage_router` at
  `/api/v1/storage` AND at `/api/v1`. The agent-compat mounts expose
  `/api/v1/files`, `/api/v1/files/{id}`, `/api/v1/usage`,
  `/api/v1/export`, `/api/v1/breakdown`, `/api/v1/upload`. Every G1
  gap applies to the `/api/v1/…` mirrors too — and any future gate
  added to the `/storage/` prefix won't automatically apply to the
  mirror because they share a router, so the fix needs to go on the
  handler, not the route.
- **Fix.** Consolidate. If agent-compat is needed, make it a thin
  alias module that reuses the gated handlers.
- **File:line.** `api/app/main.py:119-121`.
- **Effort.** 1h.

### G17. `PLAN_TIERS` and `TIER_QUOTAS` have diverged vocabularies
- **What's broken.** `routes/billing.py:313-318` defines `PLAN_TIERS`
  with `free / basic / pro / ultra`. `_tier_quotas()` (Wave 2) uses
  `free / pro / ultra / max`. `POST /billing/plan/upgrade` only accepts
  `PLAN_TIERS` keys, so a caller who asks for `max` gets 400; a caller
  who asks for `basic` gets allocated with `_estimate_storage_cost`
  pricing that nobody else in the system believes in. Billing
  reconciliation will hate this.
- **Fix.** Unify. Pick one vocabulary (Wave 2's `free/pro/ultra/max`)
  and remove the other. `_estimate_storage_cost` and `upgrade_plan`
  should read from `_tier_quotas()`.
- **File:line.** `api/app/routes/billing.py:311-318, 335-367`.
- **Effort.** 2h.

### G18. `default_storage_quota=500 MB` vs `tier_quota_free=5 GB` — two sources of truth for "free quota"
- **What's broken.** `config.py:51` and `config.py:57` both define the
  free-tier quota, at different values. `storage_plans.py:STORAGE_PLANS`
  has a third copy (500 MB). Uploads that hit `FileRecord.sum >
  settings.default_storage_quota` (fallback when no UserPlan row) 507
  at 500 MB; uploads that provisioned through `allocate_plan` get 5 GB.
- **Fix.** Drop `default_storage_quota` or make it a read-through to
  `tier_quota_free`. Same for `STORAGE_PLANS[0].storage_bytes`.
- **File:line.** `api/app/config.py:51,57`;
  `api/app/routes/storage.py:291-297`.
- **Effort.** 45m.

### G19. `pyproject.toml` has no `pytest-cov` — the project can't emit a coverage report on its own
- **What's broken.** I had to `uv add --dev coverage` just to get
  numbers. Stock check-out has no coverage tooling. CI presumably has
  none either.
- **Fix.** Add `pytest-cov` + `coverage[toml]` to `[dependency-groups.dev]`,
  wire a minimum-coverage threshold in CI.
- **File:line.** `pyproject.toml`, `.github/workflows/*.yml` (if any).
- **Effort.** 30m.

### G20. Rate limiting is global (120 req/min/IP); no per-route or per-user limits
- **What's broken.** `middleware/rate_limit.py` applies a single
  120 req/min/IP cap across every endpoint. Upload at 120/min × 1 GB
  = 2 GB/s sustained from one IP. Auth endpoints and webhooks share
  the same bucket, so a legitimate product backend pushing backups
  competes with adversarial probe traffic.
- **Fix.** Tiered limits: 30/min for uploads, 10/min for
  `billing/allocate`, exempt webhook endpoints (retries fall under one
  IP).
- **File:line.** `api/app/middleware/rate_limit.py`,
  `api/app/main.py:86`.
- **Effort.** 2h.

### G21. `allocate_plan` has no passport-format validation; accepts `../` in passport_number
- **What's broken.** Live probe:
  `POST /billing/allocate {"passport_number":"../../internal-api/admin"}`
  → `200 OK`, plan allocated with multiplier 1.0 (Eternitas unreachable
  from the fresh server, so fail-open). If Eternitas *were* reachable,
  `TrustClient.get_trust` would build the URL
  `{base}/api/v1/trust/../../internal-api/admin` — httpx may or may
  not percent-encode, depending on version; under certain configs this
  lets the attacker reach Eternitas endpoints *other than* the trust
  lookup.
- **Fix.** Validate `passport_number` against `^(ET26-|EH)[A-Z0-9-]{4,40}$`
  before allocate and in link-passport. Percent-encode via
  `httpx.URL().copy_with(path=...)` not f-string.
- **File:line.** `api/app/routes/billing.py:AllocateRequest`,
  `api/app/services/trust_client.py:139`.
- **Effort.** 45m.

### G22. No cache-warming / pre-flush strategy for trust cache on deploy
- **What's broken.** On rolling deploys, new Fargate tasks start with
  empty trust caches. The first N requests per-passport hit Eternitas
  synchronously in the request path. If Eternitas is rate-limiting,
  the deploy correlates with a spike of trust-unavailable 5xxs. Today
  the fail-open behaviour (G8) masks this.
- **Fix.** Pre-warm on startup by reading the active passport list
  from the bridge table and fetching trust for each on a background
  task (rate-limited).
- **File:line.** `api/app/main.py:39-56` (lifespan).
- **Effort.** 2h.

### G23. Webhook handlers catch every exception as 5xx, don't distinguish signer errors from code bugs
- **What's broken.** The webhook handlers raise HTTPException for
  invalid-signature / missing-secret / stale-timestamp, but let Python
  exceptions from inside the body propagate as 500. Eternitas retries
  3× on non-2xx; a deterministic code bug (say, a DB constraint
  failure) will retry 3 times with identical payloads, inflate the
  delivery count, and then deactivate Cloud as a platform.
- **Fix.** Wrap the handler body in `try/except`, 200 on unhandled
  exceptions after logging + Sentry, so Eternitas doesn't auto-disable
  us for our own bugs.
- **File:line.** `api/app/routes/webhooks.py:54-322`.
- **Effort.** 1h.

### G24. CORS: `allow_methods=["*"]`, `allow_headers=["*"]`, `allow_credentials=True`
- **What's broken.** `main.py:92-94`. Modern browsers refuse the
  `Access-Control-Allow-Origin: *` + `credentials: include` combo —
  Starlette special-cases this to echo the request origin instead,
  which means the effective policy is "any origin I see in a Request
  header can present credentials." Combined with loose origin list
  in dev mode, attackers can CSRF-with-credentials from any origin
  they can get a Windy user to visit.
- **Fix.** Explicit `allow_methods=["GET","POST","PUT","DELETE"]`,
  explicit `allow_headers=["Authorization","Content-Type","X-Service-Token"]`.
  Lock origin list to known domains.
- **File:line.** `api/app/main.py:89-95`.
- **Effort.** 30m.

---

## P2 — POLISH

### G25. README endpoint list drifts from reality
- README omits: `/api/v1/billing/plan`, `/plan/upgrade`, `/sync`,
  `/summary`, `/archive/migrate`, `/archive/retrieve/…`,
  `/analytics/*`, `/sync/status`, `/export/my-data`, `/export/{id}`,
  `/servers/deploy-fly`. The agent-compat mirrors are also missing.
- **Fix.** Regenerate from OpenAPI on every release. Add a CI check.
- **Effort.** 45m.

### G26. Missing service-token header returns 422, not 401
- **What's broken.** FastAPI renders `Header(...)` missing as
  `422 Unprocessable Entity`. Semantically this is "your request body
  is bad"; the real meaning is "you're not authorized." Tools that
  retry on 422 will spin.
- **Fix.** Wrap the dep to translate missing-header to 401.
- **Effort.** 30m.

### G27. `_estimate_storage_cost` is stuck in old pricing
- `routes/billing.py:293` uses ladder 500 MB / 5 GB / 50 GB /
  500 GB → $0/$2/$5/$10. Wave 2 quotas moved the ceilings to
  5 GB / 100 GB / 1 TB / 5 TB. Estimates are now useless to users.
- **Effort.** 30m.

### G28. `archive_retrieve` path uses `{filename:path}` converter
- Accepts slashes in the URL path. The filename is sanitized at the DB
  layer (the actual file lookup is by FileRecord.storage_key, not the
  URL filename), so not exploitable — but the `:path` converter is
  misleading and a trip hazard for the next editor.
- **Effort.** 10m.

### G29. `_upload_semaphore = asyncio.Semaphore(5)` semantically misleading
- Already captured as part of G6, but worth separate mention for
  readability. The docstring doesn't say "per-worker."
- **Effort.** 5m doc fix.

### G30. `r2_bucket` misspell and `R2_ENDPOINT` docstring drift
- `config.py:24` — "Auto-built from account ID if not set" in
  `.env.example` but `r2_endpoint_url` in code uses
  `{account_id}.r2.cloudflarestorage.com` which requires `r2_account_id`
  to be set. Won't auto-build without it. Minor but trip-hazard.
- **Effort.** 10m.

### G31. `/api/v1/status` and `/health` both exposed publicly and contain different info
- `/health` (`routes/health.py:80`) is detailed (DB status, storage
  provider, compute provider, uptime). `/api/v1/status`
  (`routes/health.py:118`) is the "public" one. Having both public
  leaks deployment metadata — storage provider, whether R2 is
  configured — to anyone on the internet.
- **Fix.** Either gate `/health` behind an internal load-balancer
  health-check source, or strip deployment info.
- **Effort.** 30m.

### G32. Trust cache doesn't honour `cache_ttl_seconds` from body
- `services/trust_client.py:170` stores `(now - (self._ttl -
  effective_ttl), info)` — the intent is to shorten cache TTL to match
  server hint, but the computation doesn't round-trip correctly for
  `effective_ttl > self._ttl`. Given TTLs are fixed at 300s today this
  never manifests, but easy to misbehave after a server-side bump.
- **Effort.** 15m + test.

### G33. `retention_cleanup` failure on startup is fire-and-forget
- `main.py:45-49` — any exception in the retention task is caught and
  logged, then swallowed. No Sentry event, no alarm, no state. If the
  R2 creds rotate and retention starts 5xx'ing, nobody finds out until
  customers complain about their "expired" files still being there.
- **Effort.** 45m.

---

## P3 — NICE-TO-HAVE

### G34. `db/engine.py` echo=False hardcoded
- No env flag to flip SQL echo on for debugging. Minor.

### G35. `http.py` HTTPBearer default `auto_error=True`
- Consistent across all auth deps, so fine. Worth an explicit
  flag rather than trusting the default.

### G36. Sentry `traces_sample_rate=0.1` hardcoded
- `main.py:31`. Should be an env var for gradual rollout tuning.

### G37. `LocalDiskProvider` writes metadata JSON beside the blob
- `providers/local_disk.py:55`. Reasonable for dev; not reachable in
  prod. Fine.

### G38. `_sanitize_filename` uses split-based path-traversal mitigation twice
- Once in `storage.py:38`, once in `archive.py:34` — duplicate.

### G39. `compute.py` has no quota / frozen gate
- Covered partially by G1; noting here for visibility. A frozen user
  can still consume GPU minutes until the next billing cycle exceeds
  quota.

---

## What I DIDN'T test (confidence caveats)

- **Production R2 behavior under load.** No real R2 bucket on hand; all
  tests ran against `LocalDiskProvider`. The `providers/r2.py` file has
  0% test coverage. If it's broken, you will find out at launch.
- **Real-world Fargate cold start latency.** In-process singletons
  (trust client, dedup set) behave obviously on a single process; the
  multi-worker scenario in G6 is inferred from code, not reproduced
  against a multi-pod deployment.
- **Load tests past 100 RPS.** `ab`/`wrk` weren't run. p50/p95/p99
  numbers in this session were anecdotal. Concurrent tests capped at
  100 parallel requests for allocate.
- **Webhook signature verification under JWS (not HMAC)**. I
  implemented HMAC only; `X-Windy-Signature: detached ES256 JWS` was
  never implemented, so no adversarial tests against it. G15 flags the
  naming collision.
- **IPv6 / international Unicode filename paths.** `_sanitize_filename`
  is ASCII-centric. A filename like `résumé.pdf` will round-trip fine
  via `UploadFile.filename` but I did not test non-Latin scripts
  through the full archive + retrieve cycle.
- **Cross-AZ RDS failover behaviour.** `db/engine.py`'s asyncpg pool
  default sizing. RDS failover will dump the pool; asyncpg reconnects
  but the first few requests after will 5xx.

---

## Appendix — supporting artefacts

- `docs/audit/endpoint-inventory.txt` — all 59 routes + auth + dep chain.
- `docs/audit/coverage-gaps.md` — per-file coverage breakdown.
- `docs/audit/adversarial-probes.md` — shell-session transcript of the
  live probes that produced G1, G9, G12, G21.

---

*Ship this after P0s are closed. P1s during launch week. Don't let the
  test-suite green light convince you the service is ready — half of
  the above issues pass every test in `api/tests/`.*
