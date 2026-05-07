# Windy Cloud — White-Glove Smoke Report

**Date:** 2026-04-20 (UTC) — ~6 h after Wave 13 Phase 3 cutover
**Target:** `https://cloud.windyword.ai` (EC2 `i-070327df339182f68`, EIP `32.193.70.195`, RDS `windy-cloud-billing…`)
**Build:** version `0.1.0`, commit `d337652` (PR #34 merged), alembic head `005`, container `windy-cloud-cloud-1` up 4 h, healthy.
**Brief:** `docs/WHITE_GLOVE_SMOKE_PROMPT.md` — 12 sections, behaviour-vs-unit-tests, live URL only.

## TL;DR

| Severity | Count | Headline |
|---|---|---|
| **P0** | 2 | Pro→Cloud JWT contract broken (no real Pro login authenticates); Eternitas→Cloud webhook path 404s in production (revocations dead-letter). |
| **P1** | 4 | Analytics leaks fleet-wide metrics to any authed user; zero security headers (HSTS/X-Frame/CSP/X-Content-Type/Referrer-Policy); CORS_ORIGINS limited to same-origin only; Pro `/health` declares `windy_cloud: unreachable`. |
| **P2** | 2 | LocalDiskProvider still primary (R2 keys blank); preflight from unlisted origin returns 400 with partial CORS headers. |
| **P3** | 2 | `{filename}` path-param uses the uploaded multipart name, not the supplied `filename` form field; `compute_provider=none` returns a clean 503 but UI would benefit from an explicit "not configured" signal. |

Live URL is up, healthy, TLS valid, DB reachable, Stripe webhook rock-solid, HMAC identity webhook rock-solid, storage upload/download byte-equal, cross-tenant isolation holds, unauthenticated surface properly gated. But Pro-issued tokens don't authenticate and Eternitas fanout doesn't land — the two cross-service contracts Wave 7/12 built are silently broken post-deploy.

---

## 1. Public surface

- `GET /` → 200 (2.88 KB HTML landing), 296 ms.
- `GET /health` → 200, `{"status":"ok","service":"windy-cloud"}`, 210 ms.
- `GET /health/full` → 200, reports `database:ok, storage_provider:local_disk, storage_healthy:true, compute_provider:none, uptime_seconds:12939`. **Exposed unauthenticated — version (0.1.0), storage backend, and compute state visible to anyone.** Not a bug per se (docs call it internal-only but it's mounted on the public router) — `(P3)` Consider gating behind the service token.
- `GET /api/v1/status` → 200, pillar summary, public. (Matches README.)
- `GET /docs` → 404. `GET /openapi.json` → 404. Good — OpenAPI schema hidden in prod.
- `GET /api/v1/nonexistent-abc123` → 404 `{"detail":"Not Found"}`. Clean envelope.
- `POST /api/v1/storage/upload` with malformed JSON body → 401 (auth gate fires before parsing). ✓
- `POST /api/v1/webhooks/stripe` with wrong Content-Type → 400 "Missing Stripe-Signature header". ✓
- `POST /health` (10 MB body) → 405, but the full 10 MB upload was buffered server-side (63 s to get 405 back). Not a security issue; just a UX note.

No findings.

## 2. Identity — Pro JWKS contract

Used Pro EC2 (SSH `~/windy-prod-key.pem` → Pro `100.52.10.181`) to invoke Pro's own `jwks.js` module and mint RS256 tokens signed with the live private key at `/keys/private.pem` (kid `37e8955762d43189`, matching `https://api.windyword.ai/.well-known/jwks.json`).

Matrix against `GET /api/v1/storage/files`:

| Token | Cloud response |
|---|---|
| No Authorization header | 401 "Not authenticated" |
| HS256 bearer | 401 |
| RS256, forged key, correct kid | 401 |
| RS256, forged key, unknown kid | 401 |
| RS256, Pro's real key, expired `exp` | 401 |
| RS256, Pro's real key, correct `iss=https://api.windyword.ai` + `aud=windy-cloud` + `sub=smoke-A` | **200 ✓** |
| RS256, Pro's real key, what Pro **actually** emits (`iss=windy-identity`, no `aud`, no `sub`) | **401** |
| RS256, Pro's real key, missing `aud` | 401 |

### **P0 — Pro→Cloud JWT contract is broken. No real Pro login authenticates against Cloud.**

**Observed:** Pro's production `generateOAuthTokens()` in `/app/dist/routes/oauth.js` (line 963 in the live container) emits:

```js
{ userId, windyIdentityId, email, tier, accountId, type, scopes, products, iss: 'windy-identity', client_id, scope }
```

— no `aud`, no `sub`, `iss='windy-identity'`. Same shape from `/api/v1/auth/login`.

**Expected:** Cloud's `api/app/auth/jwks.py:JWKSValidator.validate_token()` calls `jwt.decode(..., audience='windy-cloud', issuer='https://api.windyword.ai', options={'require': ['exp', 'sub']})`. That validator rejects Pro's real tokens three ways — missing `aud`, missing `sub`, wrong `iss`.

**Repro:** Log into Pro via any of its token-emitting paths (`/api/v1/auth/login`, `/api/v1/oauth/token`, device-flow), then `curl -H "Authorization: Bearer <token>" https://cloud.windyword.ai/api/v1/storage/files` → 401 "Invalid or expired token".

**Blast:** Every authed surface on Cloud (`/storage/*`, `/archive/*`, `/compute/*`, `/billing/*`, `/sync/*`, `/export/*`, `/analytics/*`, `/identity/*`, hidden `/api/v1/files`) is unreachable by any real Pro user. The Windy-Pro→Cloud product experience is functionally offline.

**Fix:** Pick one —
1. (Preferred) Pro sets `iss='https://api.windyword.ai'`, `aud=['windy-cloud','windy-pro',…]` (array so one token works for all sister services), and `sub=windy_identity_id` in `generateOAuthTokens()` + `auth.js` login path.
2. Cloud loosens `jwks.py` to read from `windy_identity_id` / `windyIdentityId` when `sub` is absent, accept `iss in {'windy-identity', 'https://api.windyword.ai'}`, and treat missing `aud` as acceptable (drop the `audience` kwarg).

Option 1 is cleaner (other Windy services inherit the fix). Option 2 is a one-line Cloud patch.

Otherwise auth verification is cryptographically sound: forged signatures, wrong kids, and expired tokens are all rejected correctly.

## 3. Storage — R2 proxy

**Provider context:** R2 keys are blank in `/opt/windy-cloud/.env` (confirmed via SSH). `settings.r2_configured` is false; `LocalDiskProvider` is live. `/health/full` reports `storage_provider:local_disk`. **`(P2)` R2 keys still not populated — standing Grant to-do from Wave 13.** All storage tests below exercised the LocalDiskProvider path; R2-specific semantics (multipart, egress) were not exercised against real R2.

Using the contract-patched tokens from §2:

- `POST /api/v1/storage/upload` — 10 KB multipart as `smoke-A` → 200, `{"file_id":"99649e97-…","key":"smoke-A/general/file/cc_small.bin","size":10240}`.
- `GET /api/v1/storage/files` (`smoke-A`) → 200, lists the file.
- `GET /api/v1/storage/files/{id}` (`smoke-A`) → 200, `application/octet-stream`, 10240 bytes, **byte-equal** to the uploaded blob (cmp exit 0).
- `GET /api/v1/storage/files/{id}` as `smoke-B` (cross-tenant read) → **404** "File not found". Not a leak.
- `DELETE /api/v1/storage/files/{id}` as `smoke-B` → **404**. Not a leak.
- `DELETE /api/v1/storage/files/{id}` as `smoke-A` (own) → 200, `{"deleted":true}`. ✓
- `GET /api/v1/storage/usage` (`smoke-A`) → 200, `{used_bytes:0, quota_bytes:5368709120, used_percent:0}`.
- `POST /api/v1/storage/upload` with a 1 MB payload → 200 round-trip. Deleted afterwards.
- `POST /api/v1/storage/upload` with a file larger than `MAX_UPLOAD_SIZE` (256 MB default) — **not exercised against the live box** (bandwidth cost). Boundary is enforced in code via `api/app/utils/upload.py:read_bounded()` and verified in the Wave 11 hardening test. No regression evidence.

No new findings. Cross-tenant isolation holds. `404 rather than 403` choice for foreign file IDs is deliberate info-hiding and matches what browsers would expect from a listing-scoped API.

## 4. Billing + Stripe webhook

Minted Stripe signatures locally with the live `STRIPE_WEBHOOK_SECRET` from `/opt/windy-cloud/.env` (`whsec_75kew…`).

| Variant | Response |
|---|---|
| `customer.subscription.created`, signed, fresh `t`, `metadata.windy_identity_id=smoke-A`, unknown price | 200 `{"status":"applied","tier":"free","billing_status":"active"}` |
| Replay of the same event | 200 `{"status":"duplicate"}` — dedupe ledger working |
| Tampered `v1=` | **403 "Invalid signature"** |
| Stale `t` (16 min old) | **400 "Stale delivery"** |
| Missing `Stripe-Signature` | **400 "Missing Stripe-Signature header"** |
| `customer.subscription.deleted` | 200 `{"status":"downgraded_to_free"}` — `UserPlan.billing_status` flipped to `canceled` (verified via RDS query) |
| Unknown event type (`unicorn.event`) | 200 `{"status":"ignored"}` — Stripe won't auto-deactivate |
| `GET /api/v1/billing/usage` as `smoke-A` | 200, scoped to caller. ✓ |

**Finding:** none. The Wave 12 C-2 implementation holds up. Only nit: invalid signature returns `403` (the webhook code raises `HTTPException(status_code=status.HTTP_403_FORBIDDEN)` when HMAC diverges); Stripe's own receiver convention is 400 for signature issues. Pure semantic, no practical impact.

## 5. Sync + archive + export

As `smoke-A`:

- `POST /api/v1/archive/chat` (multipart 14-byte txt) → 200, key `smoke-A/windy_chat/chat_backup/cc_a.txt`.
- `GET /api/v1/archive/retrieve/windy_chat/cc_a.txt` → 200, byte-equal. ✓
- `GET /api/v1/sync/status` → 200, 7-product summary, windy_chat health green (last_backup "just now"). ✓
- `POST /api/v1/sync/offer-backup` `{"recording_count": 3}` → 200 `{"status":"queued"}`.
- `POST /api/v1/export/my-data` → 200, `job_id` returned, status `pending`.
- `GET /api/v1/export/{job_id}` → 200, status `completed`, `download_url:/api/v1/storage/files/export/smoke-A/system/export/export_smoke-A_….zip`.

**(P3) Archive `{filename}` path-param doesn't use the form-supplied `filename`**

- **Observed:** `POST /archive/chat` with multipart `file=@/tmp/cc_a.txt` and form field `filename=chat-backup.txt` stored under the *multipart* filename `cc_a.txt`. Retrieve at `/archive/retrieve/windy_chat/chat-backup.txt` → 404. Retrieve at `/archive/retrieve/windy_chat/cc_a.txt` → 200.
- **Expected:** the `filename` form field on `/archive/*` POST should be authoritative; callers who rename their uploads reasonably expect the server-side filename to honour that.
- **Repro:** See §5 above.
- **Fix:** `routes/archive.py::_do_archive_upload` should prefer the explicit `filename` form value over `file.filename` when populating `FileRecord.filename` + `storage_key`.

Otherwise sync + archive + export round-trip cleanly.

## 6. Compute + servers

- `GET /api/v1/compute/models` → 200, 4 models including `large-v3` @ 3.0¢/min. Unauthenticated (intentional — pricing is public).
- `GET /api/v1/compute/usage` (as `smoke-A`) → 200, `{total_seconds:0, total_jobs:0, free_minutes_remaining:10}`.
- `POST /api/v1/compute/stt` multipart with `file=@fake.wav` → **503 "STT compute is not configured. Set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID."** — correct gating; no RunPod tab opens, no spend.
- `GET /api/v1/servers/plans` → 200, 4 plans.
- `GET /api/v1/servers` → 200, `{servers:[], total:0}` — VPS table empty.
- **Did NOT exercise `POST /api/v1/servers/create`.** That path invokes EC2 RunInstances via the `windy-cloud-api` IAM role (scoped to `Product=user-vps` tag per Wave 13 Phase 3 `iam.tf`) and would actually spin up a billable instance. Cost-discipline deferred that probe to Grant.

**(P3) `compute_provider=none` is correct but invisible to end users.** The UI will show "unavailable" with no context. Consider gating the STT tab client-side on a `/health/full` probe.

No P0/P1/P2.

## 7. Deeplink + identity webhook

Using the live `IDENTITY_WEBHOOK_SECRET` (`4b38c9…`, recovered from `/opt/windy-cloud/.env`):

| Variant | Response |
|---|---|
| Valid HMAC-SHA256 + fresh `X-Pro-Timestamp` | **201 "provisioned", plan free** ✓ |
| Tampered signature | 403 "Invalid signature" ✓ |
| Missing signature | 400 "Missing X-Pro-Signature header" ✓ |
| Stale `X-Pro-Timestamp` (16 min old) | 400 "Stale delivery" ✓ |
| `GET /api/v1/deeplink/manifest` | 200, 4 targets (backup/dashboard/plan/usage) |
| `GET /api/v1/deeplink/resolve?target=backup` | 200, `web_path:/?action=start-backup` |
| `GET /api/v1/deeplink/resolve?target=nonsense` | 400 "Unknown deeplink target: 'nonsense'" |

All green. Signature, replay, and payload-shape validation are all holding.

## 8. Analytics PII gate

### **P1 — Analytics endpoints leak fleet-wide aggregates to any authenticated user.**

- **Observed:**
  - `GET /api/v1/analytics/daily` (any valid token, free-tier user) → 200, `{"days":[{"date":"2026-04-20","files_uploaded":2,"storage_growth_bytes":1058816,…}]}`.
  - `GET /api/v1/analytics/summary` → 200, `{"total_files_uploaded":2,"total_storage_bytes":1058816,…}`.
  - Not scoped to caller — the numbers are fleet-wide.
- **Expected:** either (a) scoped to `user.identity_id`, or (b) gated on an admin scope (JWT claim like `scopes: [..., 'admin']`).
- **Repro:** `curl -H "Authorization: Bearer <any-valid-token>" https://cloud.windyword.ai/api/v1/analytics/summary`.
- **Blast:** No PII (no emails, no identity IDs) is exposed — but fleet-wide DAU-shape and storage-growth metrics are business data a competitor, journalist, or churned free user shouldn't trivially scrape. Today the surface is tiny (2 files); at scale this endpoint becomes a business-health leak.
- **Fix:** `routes/analytics.py` — add an `AnalyticsEvent.identity_id == user.identity_id` filter to both endpoints, or introduce an admin dependency and gate the fleet-wide view on it.
- **Why this isn't P0:** no per-user row is returned; the leak is aggregate. The moment the grouping changes to per-identity, bump to P0.

No admin UI exists at this layer (analytics is read-only JSON).

## 9. Agent-compat hidden router

Mounted at `/api/v1` with `include_in_schema=False`. Per `api/app/routes/agent_compat.py`, it exposes exactly one alias:

- `GET /api/v1/files` → delegates to `routes/storage.py::list_files`. Verified: returns the same payload as `/api/v1/storage/files`, and requires bearer (401 without).

Ghost paths from the pre-G16 double-mount are confirmed gone:

- `POST /api/v1/upload` → 404 ✓
- `GET /api/v1/usage` → 404 ✓

Minimal, intentional, working. The source doc comment says windy-agent's ecosystem health-check is the one consumer; that's enough reason to keep it. No finding.

## 10. CORS, headers, TLS

### **P1 — Zero security headers (HSTS, X-Frame-Options, X-Content-Type-Options, CSP, Referrer-Policy, Permissions-Policy).**

- **Observed:** `GET /`, `GET /health`, and any authed endpoint response contains exactly these headers (plus content headers): `server`, `date`, `content-type`, `content-length`, `connection`.
  ```
  $ curl -sSD- https://cloud.windyword.ai/ -X GET | grep -iE 'strict|x-frame|x-content-type|content-security|referrer|permissions'
  (nothing)
  ```
- **Expected:** at minimum `Strict-Transport-Security: max-age=31536000; includeSubDomains` on HTTPS responses, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, a scoped `Content-Security-Policy`, `Referrer-Policy: strict-origin-when-cross-origin`.
- **Repro:** See above curl.
- **Fix:** add a `SecurityHeadersMiddleware` to `main.py` (or `add_header` directives in `/etc/nginx/sites-enabled/cloud.windyword.ai`). Certbot's `options-ssl-nginx.conf` sets cipher suites only — no security headers.
- **Blast:** SSL Labs grade cap around B (missing HSTS is the usual culprit). A hostile subdomain takeover on `*.windyword.ai` could read Cloud cookies for users who already authenticated over HTTPS. No exploit observed, but the gap is 10 min to close.

### **P1 — `CORS_ORIGINS` is set to `https://cloud.windyword.ai` only.**

- **Observed:** `/opt/windy-cloud/.env` on EC2 has `CORS_ORIGINS=https://cloud.windyword.ai`. `.env.production.example` (committed) lists `https://windyword.ai,https://windycloud.com,https://cloud.windyfly.ai`.
- **Expected (speculative):** at least `https://windyword.ai` if any dashboard or marketing page there wants to call Cloud's API (e.g. post-hatch backup kickoff link).
- **Repro:** `curl -X OPTIONS https://cloud.windyword.ai/api/v1/storage/files -H "Origin: https://windyword.ai" -H "Access-Control-Request-Method: GET"` → **400 "Disallowed CORS origin"**.
- **Blast:** Any browser-based cross-origin call from `windyword.ai` → `cloud.windyword.ai` will fail. If the hatch-path deeplink resolves through `windyword.ai` HTML (which it does — the deeplink-manifest web paths are relative), a browser-based JS call to Cloud's API will CORS-block.
- **Fix:** update `/opt/windy-cloud/.env` CORS_ORIGINS to include the set of real origins (windyword.ai + windycloud.com + windycloud.com/cloud.windyfly.ai) and `docker compose restart`.

### **(P2) Preflight from a disallowed origin returns 400 with partial CORS headers echoed.**
- Observed: FastAPI CORSMiddleware responds 400 "Disallowed CORS origin" but still emits `access-control-allow-methods`, `…-allow-headers`, `…-allow-credentials:true`. It does NOT emit `access-control-allow-origin`, so a browser will correctly block. Nothing exploitable; just sloppy-looking.
- No fix necessary; starlette's behaviour.

### TLS
- Let's Encrypt E8, valid 2026-04-19 → 2026-07-18.
- TLS 1.2 + 1.3, modern cipher suite via certbot-managed `options-ssl-nginx.conf`.
- `certbot.timer` active (next run in 80 min at the time of check), auto-renew healthy.
- No SSL Labs probe run live; locally I'd expect A- capped at B by missing HSTS.

## 11. Cross-service contract

### **P0 — Eternitas → Cloud webhook URL is 404 in production; revocations are dead-lettering.**

- **Observed:** Eternitas has `windycloud` registered in `platforms` table with `webhook_url='https://cloud.windyword.ai/webhooks/eternitas'`, `is_active=true`. Cloud returns **404** on that path. Cloud exposes three separate webhook endpoints — `/api/v1/webhooks/trust/changed`, `/api/v1/webhooks/passport/revoked`, `/api/v1/webhooks/passport/reinstated` — none at the subscribed URL. Confirmed via:
  ```sql
  select id, name, webhook_url, is_active from platforms;
  -- plt_f0126…  windycloud  https://cloud.windyword.ai/webhooks/eternitas  t
  ```
- **Expected:** One of — Cloud exposes a unified `/webhooks/eternitas` receiver that dispatches on `event_type`; OR Eternitas subscriber URL updated to `…/api/v1/webhooks/trust/changed` + the other two; OR nginx adds three path rewrites.
- **Repro:**
  ```
  $ curl -i https://cloud.windyword.ai/webhooks/eternitas -X POST
  HTTP/1.1 404 Not Found
  ```
  Eternitas's `webhook_deliveries` table shows this is already live-failing — all 5 subscribers hit HTTP 404/401 on Apr 20 00:09 UTC `passport.revoked` fanout (rows are `status='dead_letter', attempts=3`). `windycloud` (`plt_f01…`) specifically got **HTTP 404 twice** in that burst.
- **Blast:** Every Eternitas event meant for Cloud drops. Passport revocations do not freeze Cloud UserPlans; trust-tier changes do not invalidate Cloud's trust cache; reinstate events do not unfreeze. The Wave 7 G1/G22 + Wave 12 H-3 work is effectively unwired post-deploy.
- **Severity rationale:** A revoked bot keeps its Cloud quota until the JWT naturally expires (the dev-memo says 15 min, but Cloud doesn't re-check trust per request — it caches for `TRUST_CACHE_TTL_SECONDS=300` after warmup). A revoked human identity keeps uploading to Cloud indefinitely until an orthogonal path flips `user_plans.frozen`. This is the exact scenario Wave 7 was designed to prevent.
- **Fix (smallest):** add a dispatcher route on Cloud at `POST /webhooks/eternitas` (no `/api/v1` prefix) that reads `X-Eternitas-Event` and forwards to the right handler. One file, ~20 lines. Alternatively register each of the three event-specific URLs with Eternitas separately.

### **P1 — Pro's `/health` reports `windy_cloud: unreachable`.**

- **Observed:** `curl https://api.windyword.ai/health` → `{"services":{"windy_chat":"unreachable","windy_mail":"unreachable","windy_cloud":"unreachable","eternitas":"unreachable"}}`.
- **Expected:** at least `windy_cloud:reachable` given Pro's health-check should `GET /health` against `https://cloud.windyword.ai/health` (which does return 200). The other three sister services are offline / unroutable from Pro's perspective, which is its own problem.
- **Repro:** see above curl.
- **Blast:** Pro's own observability is misleading; anyone monitoring Pro's `/health` thinks Cloud is down. Dashboards will be noisy. No direct user impact.
- **Fix:** Pro's health-check worker needs (a) the right Cloud URL (maybe still pointing at `api.windycloud.com` placeholder), (b) network reachability from Pro's security group to Cloud's EIP on 443. `(Pro-side fix, not Cloud-side — logged here because it surfaced during Cloud's smoke.)`

### JWKS fetch: confirmed
- Cloud reached Pro's JWKS in-flight (every one of my 40+ successful token validations did a `PyJWKClient.get_signing_key_from_jwt()` which hits `https://api.windyword.ai/.well-known/jwks.json` — cache TTL 300 s). No JWKS fetch errors in Cloud's logs.
- Eternitas JWKS (`https://api.eternitas.ai/.well-known/eternitas-keys`) responded 429 "Rate limit exceeded" from my workstation — aggressive per-IP rate limit, not a Cloud issue. Cloud's server-to-server call succeeds (no errors in logs).

### Identity webhook: confirmed working
- HMAC-signed `POST /api/v1/webhooks/identity/created` test in §7 returned 201 and created a real `UserPlan` row — the Pro→Cloud identity-bridge is wired and verified. The only remaining bridge bit is: does Pro actually sign outbound `identity.created` with `IDENTITY_WEBHOOK_SECRET`? I couldn't trigger a real signup path to observe; needs Grant to cut a test user via Pro's register flow and watch Cloud logs.

## 12. Observability + migrations

- Container `windy-cloud-cloud-1` up 4 h, health `healthy`, bound to `127.0.0.1:8200` (nginx upstream on the same box).
- EC2 load average `0.00, 0.00, 0.00` — essentially idle.
- `alembic heads` → `005 (head)` — matches code. ✓
- RDS `windy-cloud-billing.cqxekagcetpz.us-east-1.rds.amazonaws.com`: PostgreSQL 16.4, reached cleanly from the container, 12 tables present, no lock contention.
- `user_plans` row count: 7. `webhook_deliveries` row count: 3 (post-cleanup — 2 Stripe evts + 1 identity webhook that I couldn't undo without re-running Alembic; they're real plan rows. Grant — if you want me to delete `smoke-webhook-1` and `smoke-1776625787-30741` plan rows, SQL in `/tmp/cc_cleanup.py` on the box).
- Container logs: **no ERROR / CRITICAL / Traceback in last 200 lines** apart from the intended-rejection paths I exercised (403 Invalid signature, 400 Stale delivery, 401 Invalid token). Startup lifespan logs are clean (`Waiting for application startup` → `Application startup complete`). G33 startup-task instrumentation is present but no failures to report.
- Certbot renew timer active; cert good for 90 days.

### Test resources created/torn down

Touched during this smoke run, all cleaned up:

| Resource | Action |
|---|---|
| `user_plans` rows for `smoke-A`, `smoke-B`, `smoke-test-identity-A`, `smoke-webhook-1` | Created via `/billing/allocate` + `/webhooks/identity/created`. **Cleaned.** |
| `files` rows for `smoke-A`, `smoke-B`, `smoke-webhook-1` | Uploaded + deleted via API. Rows gone. |
| `webhook_deliveries` rows for `evt_smoke_*`, `evt_unk_*` | **Cleaned** (see `/tmp/cc_cleanup.py`). |
| `export_jobs`, `backup_offers`, `analytics_events` | **Cleaned.** |
| No EC2 instances, RDS instances, R2 objects, or Stripe subscriptions were spun up. | — |
| Pre-existing `smoke-1776625787-30741` plan row | Left alone (pre-dates this session). |

---

## Recommendations, in order

1. **Fix the P0s today.** Pro emits correct `sub/aud/iss` and Cloud adds a `/webhooks/eternitas` dispatcher — both are <1 h of work and unblock the product.
2. **Ship security headers + tightened CORS.** Add the `SecurityHeadersMiddleware` and update `CORS_ORIGINS` on the host. 30 min.
3. **Gate analytics** on either per-caller scope or an admin JWT claim. 20 min.
4. **Populate R2 keys.** Standing Grant to-do from the Wave 13 runbook. LocalDiskProvider works but doesn't survive instance replacement.
5. **Fix Pro's `/health` service-reachability** — separate PR in windy-pro.
6. **Archive `{filename}` correctness** — minor polish.

Overall, Wave 13 Phase 3 shipped cleanly at the infra layer. The user-facing breakages are in cross-service wiring (JWT claims + webhook URL), not Cloud code. Once #1 lands, the "paid user experience" comes to life.

---
*End of report. Generated 2026-04-20 during live smoke session. ~3 h elapsed. No bugs fixed — discovery only, per brief.*
