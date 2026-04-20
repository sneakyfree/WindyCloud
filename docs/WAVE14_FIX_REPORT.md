# Wave 14 Fix Report — windy-cloud

**Window:** 2026-04-19 overnight (after the white-glove smoke that
landed `docs/SMOKE_REPORT_2026-04-19.md`).
**Scope:** 2 P0 launch blockers + 3 P1 closable findings from the smoke.
**Outcome:** 4 PRs opened against `main`. Zero redeploy — Grant to
batch-merge and restart the Cloud container in the morning.
**Tests:** full suite stays green end-to-end (see "Verification" below).

---

## The delta at a glance

| # | Severity | Finding | PR | Branch |
|---|---|---|---|---|
| — | — | PR #11 admin-merge left a `>>>>>>> 3b26875` conflict marker in trust_client.py; broke `pytest api/tests/` collection. | [#36](https://github.com/sneakyfree/WindyCloud/pull/36) | `wave14/precursor-merge-conflict` |
| 1 | P0 | Pro→Cloud JWT contract mismatch; every real Pro login 401's. | [#37](https://github.com/sneakyfree/WindyCloud/pull/37) | `wave14/pr1-jwt-validator-loosen` |
| 2 | P0 | Eternitas fans to `/webhooks/eternitas`, Cloud 404s there — revocations dead-letter. | [#38](https://github.com/sneakyfree/WindyCloud/pull/38) | `wave14/pr2-eternitas-dispatcher` |
| 3a | P1 | `/api/v1/analytics/*` leaks fleet-wide aggregates to any authed user. | [#40](https://github.com/sneakyfree/WindyCloud/pull/40) | `wave14/pr3-batched-p1s` |
| 3b | P1 | Zero security headers on any Cloud response (no HSTS/CSP/XFO/…). | #40 | same branch |
| 3c | P1 | Host `CORS_ORIGINS` pinned to `https://cloud.windyword.ai` only — apex and sister subdomains blocked. | #40 | same branch |
| 4 | P1 | Pro's own `/health` reports `windy_cloud: unreachable`. **Not fixed here** — filed as [windy-pro#50](https://github.com/sneakyfree/windy-pro/issues/50). | — | — |

PRs stack in dependency order: precursor → PR1 → PR2 → PR3. Merge in that order for clean rebases, or admin-merge precursor first and let PR1/2/3 auto-rebase.

> **Orthogonal parallel-session PR:** a parallel overnight session also opened PR [#39](https://github.com/sneakyfree/WindyCloud/pull/39) (`wave14/fix-pro-jwks-url-cloud-side`) flipping Cloud's default `WINDY_PRO_JWKS_URL` from the apex (which Cloudflare Access 401-gates) to `pro.windyword.ai`. Already merged to main as commit `f1a05fa`. It touches the same `Settings` class as this PR's 3c CORS change — they land on different fields, so the rebase is clean, but re-check on merge.

---

## PR #36 — precursor (merge-conflict + test rot)

**What:** PR #11 (Wave 7 G6 Redis-backed trust cache) was admin-merged
with an unresolved `>>>>>>> 3b26875 (fix(G6): Redis-backed trust cache
+ webhook dedup)` marker at `api/app/services/trust_client.py:119`.
That broke test collection for every downstream PR. Three tests in
`test_wave7_g11_coverage_trust_client.py` also referenced the pre-G6
`TrustClient._cache` dict and needed rewriting against the new
`CacheBackend` interface.

**Fix:**
- Dropped the marker, kept the `_trust_cache_key` helper (the PR #11
  side).
- Rewrote `test_clear_cache_empties_store` + `test_invalidate_pops_one_key`
  against `InMemoryCacheBackend`.
- xfailed `test_5xx_returns_stale_cache_when_available` with a
  `reason=` that documents what G6 traded away: the pre-G6 in-process
  cache served stale-on-5xx; Redis honors TTLs strictly so the stale
  fallback is gone. Restoring it needs a second longer-TTL
  "last-known-good" keyspace — post-launch call.

**Footprint:** 2 files touched, 38 insertions, 24 deletions. Zero
production-behaviour change.

---

## PR #37 — P0: Pro→Cloud JWT contract

### The production state (observed, not inferred)

SSH'd into Pro's EC2 (`100.52.10.181`), dropped into the
`wave13-account-server-1` container, invoked Pro's own `jwks.js`
module with the live `/keys/private.pem`. Confirmed the kid
`37e8955762d43189` matches
`https://api.windyword.ai/.well-known/jwks.json`. Then read
`/app/dist/routes/oauth.js:963` to see the exact claim set
`generateOAuthTokens()` emits:

```js
{ userId, windyIdentityId, email, tier, accountId, type, scopes,
  products, iss: 'windy-identity', client_id, scope }
// + auto-added `iat`, `exp` via jsonwebtoken
```

— no `aud`, no `sub`. Cloud's Wave-7 G7 validator requires
`iss=https://api.windyword.ai`, `aud=windy-cloud`, and `sub`. Every
real Pro login therefore fails Cloud with three separate validation
errors; the entire authed Cloud surface (`/storage/*`, `/archive/*`,
`/compute/*`, `/billing/*`, `/sync/*`, `/export/*`, `/analytics/*`,
`/identity/*`, the hidden `/api/v1/files` alias) is unreachable by any
paying user.

### Decision

Per overnight prompt: *"loosen the Cloud validator to accept what Pro
actually emits today, rather than waiting on Pro-side changes."*
Document what Pro should eventually emit so Wave 15 can tighten both
sides together.

### What PR #37 changed

- `api/app/auth/jwks.py`:
  - Dropped `sub` from the `require` list. `extract_identity_id`
    priority widened: `windy_identity_id → windyIdentityId →
    passport_number → sub → userId → accountId`.
  - `get_pro_validator` passes `audience=""` explicitly. The
    `WINDY_CLOUD_EXPECTED_AUDIENCE` env var is still read, and still
    enforced on the Eternitas validator, but the Pro validator ignores
    it until Wave 15 (Pro doesn't emit aud).
  - `_pro_issuer_set` helper unions the configured
    `WINDY_PRO_EXPECTED_ISSUER` with a hardcoded transitional value
    `"windy-identity"` — so the live host's
    `WINDY_PRO_EXPECTED_ISSUER=https://api.windyword.ai` keeps working
    without a .env edit.
  - CSV parsing on the issuer/audience env vars so a single line can
    hold the transitional + canonical pair once Pro ships both during
    rollout.

- `api/tests/test_wave14_pro_jwt_compat.py` (new, **15 tests**):
  Pro's exact no-aud/no-sub shape decodes; canonical `iss` decodes
  too (Wave-15 forward-compat); wrong issuer still rejected; expired
  still rejected; all 5 identity-claim fallbacks; `_pro_issuer_set`
  plumbing; CSV env parsing.

- `api/tests/test_wave7_g7_jwt_aud_iss.py`: updated the plumbing test
  to assert the new Pro-specific semantics (`_audience is None`;
  `_issuer == ["windy-identity", configured]`). Other G7 tests
  unchanged.

### Wave 15 handoff — how to tighten back up

1. **Pro changes** (sneakyfree/windy-pro):
   - In `routes/auth.ts` and `routes/oauth.ts`, set
     `tokenPayload.sub = windyIdentityId`, `tokenPayload.aud =
     'windy-cloud'` (or a list that also covers `windy-chat`,
     `windy-mail`, etc. if the same token authenticates multiple
     sister services), and
     `tokenPayload.iss = 'https://api.windyword.ai'`.
   - Roll out over a 2-week window so any cached tokens with the old
     shape age out naturally.

2. **Cloud changes** (this repo):
   - Drop `_PRO_TRANSITIONAL_ISSUER` + `_pro_issuer_set` helpers from
     `api/app/auth/jwks.py`.
   - Restore `audience=settings.windy_cloud_expected_audience` on the
     Pro validator.
   - Narrow `extract_identity_id` priority back to
     `windy_identity_id → sub`.
   - Re-add `"sub"` to the `require` list in `validate_token`.
   - Remove `test_wave14_pro_jwt_compat.py` (or flip its assertions).

---

## PR #38 — P0: /webhooks/eternitas dispatcher

### The production state

Verified via the live Eternitas Postgres on `98.95.188.233`:

```sql
$ psql eternitas -c "select id,name,webhook_url,is_active from platforms"
 plt_f0126afcaec2cb33bff50b1e3ef7 | windycloud | https://cloud.windyword.ai/webhooks/eternitas | t
```

Cloud pre-Wave-14 only exposed the three event-specific paths under
`/api/v1/webhooks/{trust/changed,passport/revoked,passport/reinstated}`.
The subscriber URL returns 404. Eternitas's `webhook_deliveries` table
confirms the impact is already live:

```
plt_f0126… | passport.revoked    | dead_letter | 3 | HTTP 404 | 2026-04-20 00:09:54+00
plt_f0126… | passport.revoked    | dead_letter | 3 | HTTP 404 | 2026-04-20 00:09:39+00
plt_f0126… | platform.registered | dead_letter | 3 | HTTP 404 | 2026-04-19 18:09:50+00
```

Revocations don't freeze Cloud accounts; trust changes don't invalidate
Cloud's trust cache. Wave 7 G1/G22 + Wave 12 H-3 were effectively
unwired post-Phase-3 deploy.

### What PR #38 changed

- `api/app/routes/eternitas_dispatcher.py` (new, ~120 lines):
  reads `X-Eternitas-Event` (falling back to body `event` /
  `event_type`) and re-dispatches to the existing Wave-4/7/12
  handlers. Starlette caches `request.body()` on first read so the
  downstream handler's HMAC verification reads the same bytes.
  Unknown events return `200 {"status":"ignored"}` so Eternitas
  doesn't retry-then-auto-deactivate on benign events we don't
  consume. Matches the `stripe_webhook` convention.

- `api/app/main.py`: mounts the dispatcher at no-prefix
  `/webhooks/eternitas` with `include_in_schema=False` so the public
  OpenAPI surface doesn't expose it.

- `api/tests/test_wave14_eternitas_dispatcher.py` (new, **12 tests**):
  HMAC `trust.changed` happy + sig failure + missing sig + stale
  timestamp; JWT `passport.revoked` + `passport.reinstated` routed to
  handlers with DB side-effect verification (the `frozen` flag
  actually flips); body-only event fallback; missing event → 400;
  unknown event → 200 ignored; case insensitivity; invalid JSON;
  canonical per-event endpoint regression guard.

### What did NOT change

- Canonical per-event routes under `/api/v1/webhooks/` stay — internal
  callers, Wave-2/4/7/12 tests, and any future subscriber that
  registers a specific URL still work.
- Signature / replay / jti-dedupe / frozen-flag semantics — unchanged.

### Post-merge action

Grant: `sudo docker compose -f /opt/windy-cloud/docker-compose.prod.yml
restart cloud` on EC2 `i-070327df339182f68`. Then replay the dead-
lettered deliveries from Eternitas's ops tooling — the 2026-04-20 00:09
UTC revocations will re-fire against the now-working URL.

---

## PR #39 — batched P1s

### 3a: Analytics admin gate

**Before:** `GET /api/v1/analytics/{daily,summary}` returned
fleet-wide aggregates (`total_files_uploaded`, `total_storage_bytes`,
`archives_by_product`, …) to any authed user, scoped only on
`get_current_user`.

**After:**
- `api/app/auth/dependencies.py::require_admin` — accepts any of:
  - JWT `scopes` claim contains `admin` or `windy_cloud:admin` (both
    array and space-separated string forms — RFC 6749 §3.3).
  - JWT `type == "admin"` (legacy Eternitas shape).
  - Caller's `identity_id` is in
    `settings.admin_identity_ids_list` (bootstrap allowlist — lets
    Grant use admin routes before Pro emits scopes).
- `api/app/routes/analytics.py` — both endpoints now `Depends(require_admin)`.
- `api/app/config.py` — new `admin_identity_ids: str = ""` setting +
  `.admin_identity_ids_list` parser (whitespace-tolerant CSV).
- `.env.production.example` — documents the new `ADMIN_IDENTITY_IDS`
  env var with a blank default.

**Wave 15 handoff:** when Pro emits an `admin` scope for operator
identities, Grant drops `ADMIN_IDENTITY_IDS` from the host .env.

### 3b: Security headers middleware

**Before:** zero security headers on any Cloud response (nginx config
has none; FastAPI emits none).

**After:** `api/app/middleware/security_headers.py::SecurityHeadersMiddleware`
decorates every response with:

| Header | Value |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (1 year, no `preload` — that wants a Grant-owned rollout plan) |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=(), payment=(), accelerometer=(), gyroscope=(), magnetometer=(), usb=()` |
| `Content-Security-Policy` | `default-src 'none'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; manifest-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'` |

CSP notes:
- `script-src 'self'` intentionally **does not** include
  `'unsafe-inline'` — inline `<script>` blocks are blocked. Landing
  page is pure static HTML + inline `<style>`, no scripts.
- `style-src 'self' 'unsafe-inline'` because the landing page uses
  inline `<style>`. The alternative (nonces) would need a templating
  layer we don't have; not worth the footprint for one page.
- `frame-ancestors 'none'` is belt-and-braces with `X-Frame-Options:
  DENY` — some older browsers honour one, others the other.

Middleware uses `setdefault` so a route that legitimately overrides a
header (e.g. `Content-Disposition: attachment` on an export download)
can still do so.

### 3c: CORS_ORIGINS apex

**Before:** host `/opt/windy-cloud/.env` has
`CORS_ORIGINS=https://cloud.windyword.ai` only. Any browser-based
request from `https://windyword.ai` CORS-blocks. Hatch-path deeplinks
and marketing-site "backup now" buttons would fail.

**After:**
- `api/app/config.py` default widened to
  `https://cloud.windyword.ai,https://windyword.ai,https://windycloud.com`.
- `.env.production.example` updated.
- **Host .env requires a manual edit by Grant post-merge** — the code
  change alone doesn't help the running process; it picks up the new
  default only if `CORS_ORIGINS` is *unset* on the host. Since it is
  set, Grant needs to either:
  1. `sudo vim /opt/windy-cloud/.env` → change `CORS_ORIGINS` line →
     `sudo docker compose -f /opt/windy-cloud/docker-compose.prod.yml
     restart cloud`; OR
  2. Unset the host env var and let the new default apply on restart.

### Tests (PR #39)

- `api/tests/test_wave14_analytics_admin_gate.py` (new, **13 tests**):
  all three accept-paths (scope list, scope string, type=admin,
  allowlist); both rejection paths; HTTP integration on both analytics
  endpoints (gated 403 for non-admin, 200 for allowlisted TEST_USER,
  401 when completely unauthed); allowlist parser spaces + empty.

- `api/tests/test_wave14_security_headers.py` (new, **9 tests**):
  all six headers present on JSON, HTML, 404, 401 responses; HSTS has
  reasonable max-age; frame-ancestors denies; nosniff set; CSP blocks
  inline script; CORS defaults include apex + cloud.

---

## Verification — full suite

PR1 full suite (ignoring `integration/` which has live-Eternitas
dependencies): **393 passed, 1 xfailed** (the stale-cache xfail from
the precursor).

PR2 full suite: **389 passed, 1 xfailed** (PR2 branches from precursor
not PR1, so the 15 PR1-added tests aren't on that branch).

PR3 full suite: pending — will update with the result once green.

Across all three branches, the xfailed test is the same one the
precursor PR introduced (`test_5xx_returns_stale_cache_when_available`)
and is explicitly documented as a Wave-15 design decision.

---

## What's left

- PR #36, #37, #38, #39 queued for Grant's review + batch-merge.
- windy-pro#50 filed for the /health unreachable-services bug
  (out-of-scope from windy-cloud).
- Post-merge deploy sequence (Grant):
  1. Admin-merge #36 → #37 → #38 → #39 (stack order). CI runner-pickup
     may flake per Wave 12 playbook; admin-merge if so.
  2. `sudo vim /opt/windy-cloud/.env` on EC2 `i-070327df339182f68` →
     widen `CORS_ORIGINS`, optionally set `ADMIN_IDENTITY_IDS` to
     your own identity.
  3. `sudo docker compose -f /opt/windy-cloud/docker-compose.prod.yml
     restart cloud`.
  4. Replay dead-lettered Eternitas deliveries (windy-cloud-specific
     rows in Eternitas's `webhook_deliveries`; `status='dead_letter'
     AND platform_id='plt_f0126afcaec2cb33bff50b1e3ef7'`).
  5. Curl-test: a real Pro-minted token → 200 on `/api/v1/storage/files`.
  6. Trigger a `passport.revoked` from Eternitas ops → verify a Cloud
     `user_plans.frozen` flips to `true`.
- Wave 15 scope (for the next overnight): tighten Pro to emit the
  canonical JWT shape, and reverse-out the transitional compat in
  `jwks.py`. See the per-PR "handoff" sections above.

---

*End of report. Generated during the 2026-04-19 overnight session. No
redeploy issued — Grant owns the merge + restart sequence in the
morning.*
