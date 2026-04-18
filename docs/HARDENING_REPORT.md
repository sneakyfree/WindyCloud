# Wave 11 — Adversarial Hardening Report

**Date:** 2026-04-18
**Branch:** `wave11/hardening`
**Environment:** local stack (uvicorn + sqlite + local-disk storage + mock
compute); fake Eternitas Trust API stood up on `:8500`; fake Eternitas
JWKS stood up on `:8501`.
**Author:** hostile-QA pass (Claude Opus 4.7, 1M context)

---

## TL;DR — findings in priority order

| # | Severity | Finding |
|---|---|---|
| 1 | **Critical** | `/api/v1/archive/*` endpoints **bypass UserPlan quota**. Only `/storage/upload` checks. A service-token caller (agent / mail / word) can push past the user's plan quota unchecked. |
| 2 | **Critical** | No `/api/v1/webhooks/stripe` endpoint exists. `.env.production.example` declares `STRIPE_WEBHOOK_SECRET` but no route consumes it. |
| 3 | **High**    | No `passport.reinstated` webhook. Once a passport is revoked, the only un-freeze path is a direct DB write. |
| 4 | **High**    | Frozen accounts are blocked from **reads** too (archive/retrieve, storage/files). If product policy says "frozen users can still read their historical data," the current `require_not_frozen` gate is too wide. |
| 5 | **Medium**  | `POSTGRES_PASSWORD` in `.env` is rejected by pydantic `Settings` (`extra_forbidden`). Same var is used by `docker-compose.yml`. `.env` cannot be shared between compose and the app. |
| 6 | **Medium**  | `docker compose build` needs buildx ≥ 0.17; the dev machine's version is older, so `docker compose up -d` fails at build time on this host. CI image is GHCR-pulled so prod isn't affected — but the developer quickstart doesn't work out of the box. |
| 7 | **Low**     | `MAX_UPLOAD_SIZE=256 MB` is the binding limit for a single request. The prompt's "upload a 5 GB file (free-tier limit)" cannot succeed in one request — free-tier 5 GB is only reachable by many smaller uploads. |
| 8 | **Low**     | Terraform `fmt` was out of spec on `rds.tf` (auto-fixed in this PR). `terraform plan` requires real AWS STS auth — cannot complete on a dev box without creds. |
| 9 | **Info**    | Starter Terraform module has no Secrets Manager resources, no CloudWatch Log Group, no Route53 record. IAM refers to `windy-cloud/*` secrets that don't exist yet. Wave 10 work. |
| 10 | **Info**   | `windycloud://` custom-URL scheme is **not** registered on macOS (`open windycloud://dashboard` → `kLSApplicationNotFoundErr`). Scheme registration is the Windy Pro Electron app's job (already noted in Wave 8 PR). |

---

## 1. Stack boot

### 1.1 `docker compose up -d` — **blocked**

```
 Image windy-cloud-cloud  Building
 Image windy-cloud-web    Building
compose build requires buildx 0.17.0 or later
```

Installed buildx is older on this dev host. **Finding #6.** The prompt asked
for docker-compose; we fell back to running `uv run uvicorn` directly
against local-disk storage. Functionally equivalent for these tests
(same routes, same providers, same HMAC logic), but with SQLite in
place of Postgres.

### 1.2 uvicorn via `uv run`

```bash
IDENTITY_WEBHOOK_SECRET=wave11-identity-hmac-secret-deterministic \
SERVICE_TOKEN=wave11-service-token-deterministic \
ETERNITAS_WEBHOOK_SECRET=wave11-eternitas-hmac-secret-deterministic \
USE_MOCK_PROVIDERS=true \
ETERNITAS_USE_MOCK=false \
ETERNITAS_URL=http://127.0.0.1:8500 \
ETERNITAS_JWKS_URL=http://127.0.0.1:8501/.well-known/eternitas-keys \
uv run uvicorn api.app.main:app --host 127.0.0.1 --port 8200
```

Health:

```json
{
  "status": "ok", "service": "windy-cloud", "version": "0.1.0",
  "database": "ok",
  "storage_provider": "local_disk", "storage_healthy": true,
  "compute_provider": "mock", "compute_healthy": true
}
```

### 1.3 `.env` / Settings drift — **Finding #5**

Populating `.env` with `POSTGRES_PASSWORD=...` (the var `docker-compose.yml`
already uses) aborts startup:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
postgres_password
  Extra inputs are not permitted [type=extra_forbidden,
  input_value='wave11local', input_type=str]
```

The app's `Settings` defaults to `extra="forbid"` — so any key in `.env`
that isn't a field errors out. `POSTGRES_PASSWORD` is needed by
`docker-compose.yml` but not by the app. A single shared `.env` cannot
satisfy both. Wave 12 fix: either `model_config = SettingsConfigDict(extra="ignore")` or split into `.env.compose` and `.env.app`.

---

## 2. Storage roundtrip — byte-equality

All roundtrips used `POST /api/v1/archive/chat` (service-token auth,
Windy Chat archive flow). Downloads verified by sha256-ing the file on
disk under `data/storage/{identity}/…` against the original input.

| # | Size | Upload path | Upload HTTP | SHA-256 IN | SHA-256 OUT | Verdict |
|---|---|---|---|---|---|---|
| 3.1 | 1 KB | `/api/v1/archive/chat` | 200 | `f37e…73c` | `f37e…73c` | ✅ byte-equal |
| 3.2 | 100 MB | `/api/v1/archive/chat` | 200 | `3c74…03e8` | `3c74…03e8` | ✅ byte-equal |
| 3.3 | 5 GB single-request | — | N/A | — | — | ❌ **structurally impossible** — see §3.3 |
| 3.4 | 5.1 GB single-request | — | N/A | — | — | ❌ **structurally impossible** — see §3.4 |

### 3.3 / 3.4 — 5 GB single request cannot exist — **Finding #7**

Config cap `MAX_UPLOAD_SIZE=268_435_456` (256 MB) is enforced in
`api/app/utils/upload.py::read_bounded()`, which raises HTTP 413
mid-stream. Probe:

```
POST /api/v1/archive/chat (280 MB payload)
→ HTTP 413 {"detail":"File exceeds maximum size of 268435456 bytes"}
```

So "free-tier 5 GB" is only reachable by ≥ 20 × ≤ 256 MB uploads.
Treating the 5 GB limit as a single-upload quantity is a doc bug —
the storage pillar is quota-based, not single-request-based.

### 3.5 Corrupt `Content-Length` — clean rejection

| Variant | HTTP | Body |
|---|---|---|
| `Content-Length: 0` with non-empty body | 400 | `Invalid HTTP request received.` |
| `Content-Length: 1073741824` with tiny body | 400 | `{"detail":"There was an error parsing the body"}` |

Uvicorn + Starlette both fail closed — no crash, no partial-write.

### 3.6 Concurrent uploads race — **no race**

10 × 256 KB uploads fired in parallel from a single identity via
`/api/v1/archive/chat`. Result:

```
10 x HTTP 200
DB rows: count=10, sum_bytes=2621440
Disk files (non-meta): 10
Disk bytes:             2621440
```

DB totals match disk totals match `10 × 256 KB` exactly — no
double-accounting, no orphaned storage, no missed FileRecord row.

### 3.7 Quota enforcement on `/storage/upload` — **works**

The `/storage/upload` endpoint (unlike `/archive/*`) enforces
`UserPlan.quota_bytes`. Covered by `api/tests/hardening_wave11.py::
test_storage_upload_enforces_free_tier_quota` — first 3 KB under a
4 KB quota returns 200, second 2 KB pushes total over → HTTP 507
with `"quota exceeded"`.

### 3.8 **`/archive/*` bypasses quota — Finding #1**

Read-through of `api/app/routes/archive.py::_do_archive_upload` (lines
113–176): no `select(UserPlan)`, no quota check. Only the
`MAX_UPLOAD_SIZE` per-request cap guards it. Test proves the bypass:
`test_archive_upload_bypasses_user_plan_quota` uploads 2 KB to
`/archive/chat` under a 1 KB `default_storage_quota` and gets HTTP
200. This is a **service-to-service** path (agent / mail / word / code
archive backups), so it's not directly user-facing, but it does mean
an upstream bug in one of those products can silently consume more of
a user's plan than the user has paid for.

**Fix:** lift the quota check from `storage.py` into a shared helper
and call it from `_do_archive_upload` too.

---

## 4. Billing allocation

Service-token allocate, no passport, baseline tier quotas:

```
tier=free  → {"plan_id":"free",  "quota_bytes":5368709120}      # 5 GB
tier=pro   → {"plan_id":"pro",   "quota_bytes":107374182400}    # 100 GB
tier=ultra → {"plan_id":"ultra", "quota_bytes":1099511627776}   # 1 TB
tier=max   → {"plan_id":"max",   "quota_bytes":5497558138880}   # 5 TB
tier=platinum → HTTP 400 "Unknown tier: platinum"
```

All four tiers match the configured `TIER_QUOTA_*` env values exactly.
Unknown tier cleanly rejected.

### 4.1 Eternitas trust multiplier — **uplift works, throttle works**

Stood up a minimal fake Eternitas at `127.0.0.1:8500` returning a canned
`tier_multiplier` per env. Restarted the API with
`ETERNITAS_USE_MOCK=false` so `allocate_plan` consults the live API.

| Scenario | Base tier | Mult | Expected | Actual |
|---|---|---|---|---|
| No passport | pro (100 GB) | 1.0 | 100 GB | `107374182400` bytes ✅ |
| Exceptional passport | pro (100 GB) | 5.0 | 500 GB | `536870912000` bytes ✅ |
| Poor passport | pro (100 GB) | 0.5 | 50 GB | `53687091200` bytes ✅ |
| Poor passport | ultra (1 TB) | 0.5 | 512 GB | `549755813888` bytes ✅ |

Multiplier logic is exact. `UserPlan.trust_multiplier_at_allocation`
is persisted for audit per spec.

---

## 5. Passport revocation freeze cycle

Minted an ES256 key, published JWKS at `127.0.0.1:8501`, signed a
`passport.revoked` JWT with `passport_number=ET-REVOKE-001`, `exp=now+300`.

| Step | Request | HTTP | DB state |
|---|---|---|---|
| Link passport + allocate free plan | service-token | 200 | `frozen=False` |
| Fire `/webhooks/passport/revoked` with signed JWT | 200 `{"status":"frozen"}` | | `frozen=True` ✅ |
| Tamper last byte of token | 403 `Signature verification failed` | | `frozen=True` (no change) ✅ |
| `/archive/chat` upload for frozen identity | 403 `frozen_account` | | ✅ uploads blocked |
| `/webhooks/passport/reinstated` | 404 `Not Found` | | ❌ **endpoint missing** |

### 5.1 Un-freeze is not wired — **Finding #3**

There is no `passport.reinstated` / `account.unfreeze` route. Once
Eternitas revokes a passport, the only way back is a manual SQL
`UPDATE user_plans SET frozen=false`. That's acceptable for genuinely
permanent revocations but doesn't match the reinstatement case Wave 2
contracted for.

### 5.2 Reads during freeze — **Finding #4**

`require_not_frozen` is applied to every read route (`list_files`,
`archive/retrieve`, `download_file`). A frozen account cannot **read**
its own data either. The product spec in `DNA_STRAND_MASTER_PLAN.md`
doesn't explicitly call this either way. If the intent is
"suspended-but-recoverable," reads should still work and the gate
should split into write-only. If the intent is "permanent
revocation = digital death," current behavior is correct.

---

## 6. Deep-link reality check

### 6.1 Backend resolver — works

All four targets return 200 with the documented canonical path;
unknown target is 400:

| target | `web_path` |
|---|---|
| dashboard | `/` |
| backup | `/?action=start-backup` |
| usage | `/billing` |
| plan | `/billing?view=upgrade` |
| evil-target | HTTP 400 `Unknown deeplink target: 'evil-target'` |

### 6.2 OS-level dispatch — **not registered** (expected)

```
$ open windycloud://dashboard
No application knows how to open URL windycloud://dashboard
(kLSApplicationNotFoundErr)
```

Scheme registration is owned by the Windy Pro Electron app (Wave 8 PR #29
Grant to-do). Not a bug in `windy-cloud`.

---

## 7. Stripe webhook replay + tamper — **endpoint doesn't exist** (Finding #2)

```
$ curl -X POST http://localhost:8200/api/v1/webhooks/stripe \
    -H "Stripe-Signature: t=0,v1=bogus" -d '{}'
HTTP 404 {"detail":"Not Found"}
```

`.env.production.example` declares `STRIPE_WEBHOOK_SECRET`; DEPLOY.md §4
promised "placeholder route + secret rotation." Neither exists in the
codebase. The secret is dead config. **Fix:** build the endpoint
(Stripe-Signature verify + idempotency-key dedupe + the
`customer.subscription.*` events listed in DEPLOY.md).

---

## 8. Terraform dry-run

```
$ terraform init -backend=false
Terraform has been successfully initialized!

$ terraform validate
Success! The configuration is valid.

$ terraform fmt -check
rds.tf   ← 1 file out of spec   ← auto-fixed in this PR

$ terraform plan (AWS_ACCESS_KEY_ID=AKIAFAKE...)
│ Error: Retrieving AWS account details: validating provider credentials:
│ retrieving caller identity from STS: operation error STS: GetCallerIdentity,
│ https response error StatusCode: 403 InvalidClientTokenId
```

Plan cannot complete without real AWS STS auth — expected on a dev
box. The module is structurally valid.

### 8.1 Gaps in the starter module (Finding #9, info)

Intentional Wave 10 follow-ups, not regressions:

- No `aws_secretsmanager_secret` resources. `iam.tf` grants
  `secretsmanager:GetSecretValue` on `arn:...:windy-cloud/*` but the
  secrets themselves aren't provisioned here — they're expected to be
  created manually or via a separate stack.
- No `aws_cloudwatch_log_group`. API writes to stdout → picked up by
  the CloudWatch agent under the instance profile, not an explicit
  log group.
- No Route53 record. The older `deploy/aws-terraform/main.tf` has one
  (and DEPLOY.md references it) but the new module doesn't. DNS wiring
  is deferred to manual + terraform-import later.

None of these block a first apply; they'll be fast follow-ups.

---

## 9. Test suite posture

- **337 passed** — full non-integration suite (`pytest api/tests/ --ignore=api/tests/integration`).
- **5 new wave11 probes** — `api/tests/hardening_wave11.py` (gated behind `-m wave11`, default run skips).
- `uv run ruff check api/` — clean.

### Wave 11 probes (`pytest -m wave11`)

| Test | Asserts |
|---|---|
| `test_storage_upload_enforces_free_tier_quota` | `/storage/upload` 507 when UserPlan quota exceeded |
| `test_storage_upload_rejects_oversized_single_request` | 413 when body > MAX_UPLOAD_SIZE |
| `test_archive_upload_bypasses_user_plan_quota` | Documents Finding #1 (current wrong behavior) |
| `test_passport_revoked_webhook_signature_replay` | Missing token 400, garbage token 403 |
| `test_identity_created_webhook_replay_rejected` | Stale X-Pro-Timestamp 400 "stale delivery" |

Two scenarios in the prompt were **already covered by the default
suite** and flagged in the hardening file as redundant rather than
duplicated:

- Concurrent-upload quota-accounting race — verified on the live stack
  (§3.6) instead of a fixture; the pytest fixture shares one
  `db_session` across the parallel requests, so an in-fixture repro
  tests session-sharing behavior, not the real server.
- Full passport-revoke→freeze→reinstate cycle — already in
  `test_wave2_frozen.py`. The conftest overrides
  `require_not_blocked_for_write` with a passthrough, so a fixture
  repro here would only test the override, not the gate. Live-stack
  curl evidence in §5 above instead.

---

## 10. Recommended Wave 12 backlog

1. **Lift quota check from `storage.py` into `_archive_upload`.**
   (Finding #1.) Single shared helper; gate both paths identically.
2. **Build the `/api/v1/webhooks/stripe` endpoint.** (Finding #2.)
   Stripe-Signature HMAC, idempotency-key dedupe table, handlers for
   the events listed in DEPLOY.md §4.
3. **Add `/api/v1/webhooks/passport/reinstated`.** (Finding #3.)
   Mirrors `passport/revoked` — signed ES256 JWT, flips
   `UserPlan.frozen=False`, logs + notifies.
4. **Decide the reads-while-frozen policy.** (Finding #4.) If
   "frozen = read-only," split `require_not_frozen` into a read-safe
   and a write-blocking variant.
5. **Settings extras tolerance.** (Finding #5.) `extra="ignore"` on
   `Settings` so one `.env` can serve both `docker-compose` and the app.
6. **Document `.env.example` accurately.** Remove
   `DATABASE_URL=sqlite+aiosqlite:///data/windy_cloud.db` as the prod
   default; that trap is what caused the Wave 9 CI sqlite failure.
7. **Fill out the Terraform module.** Add Secrets Manager resources,
   explicit CloudWatch Log Group, Route53 record (mirrored from the
   old prototype).
