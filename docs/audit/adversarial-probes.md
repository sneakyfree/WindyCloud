# Adversarial probe transcripts — Wave 7

Live probes against a development instance started as:

```
IDENTITY_WEBHOOK_SECRET=probe-hmac-secret \
  SERVICE_TOKEN=probe-service-token \
  ETERNITAS_WEBHOOK_SECRET=probe-eternitas \
  ETERNITAS_URL=http://localhost:8500 \
  ETERNITAS_USE_MOCK=false \
  DEV_MODE=true \
  uv run uvicorn api.app.main:app --port 8299 --log-level warning
```

Health confirmed `{"status":"ok","service":"windy-cloud","version":"0.1.0","database":"ok","storage_provider":"local_disk","storage_healthy":true,"compute_provider":"none","compute_healthy":false}`.

---

## 1. Missing / invalid / oversized auth

```
GET  /api/v1/billing/usage   (no header)       → 401
GET  /api/v1/storage/files   (no header)       → 401
GET  /api/v1/servers         (no header)       → 401
GET  /api/v1/sync/status     (no header)       → 401
GET  /api/v1/storage/files   Bearer deadbeef   → 401
```
Good — JWT gate holds on invalid tokens.

## 2. HTTP method abuse

```
TRACE   /health → 405
CONNECT /health → 405
PATCH   /health → 405
```
No unexpected methods.

## 3. Documentation / spec endpoints exposed

```
GET /docs         → 200
GET /redoc        → 200
GET /openapi.json → 200
```
**GAP G9.** Full API surface — including service-token endpoints and
webhook shapes — is public in prod by default.

## 4. Webhook endpoints, adversarial inputs

```
POST /api/v1/webhooks/identity/created  (malformed JSON, wrong sig)
  body: {not valid json}  X-Windy-Signature: beef
  → 403 {"detail":"Invalid signature"}          ✓ signature checked first

POST /api/v1/webhooks/passport/revoked  (no token, no auth)
  body: {"passport_number":"EPT-99","reason":"none"}
  → 400 {"detail":"Missing signed token"}       ✓ token required
```

## 5. Service-token endpoints

```
POST /api/v1/billing/allocate  (missing X-Service-Token)
  → 422 [field_required]                        GAP G26 — should be 401
POST /api/v1/billing/allocate  (wrong token)
  → 401 {"detail":"Invalid or missing service token"}  ✓
```

## 6. Path traversal + dangerous passport numbers

```
GET /api/v1/archive/retrieve/windy_code/../../../etc/passwd
  Bearer fake → 404                             ✓ DB-backed filename lookup
                                                  short-circuits on unknown
GET /api/v1/archive/retrieve/windy_code/..%2F..%2F..%2Fetc%2Fpasswd
  → 401 (no auth override in this test)         ✓

POST /api/v1/billing/allocate
  body: {"windy_identity_id":"ssrf-test","tier":"free",
         "passport_number":"../../internal-api/admin"}
  X-Service-Token: probe-service-token
  → 200 {"plan_id":"free","quota_bytes":5368709120,"tier":"free",
         "identity_id":"ssrf-test"}
```
**GAP G21.** Passport format never validated. Live probe got a plan
allocated against a path-traversal string. If Eternitas had been
reachable from the probe host, `{base}/api/v1/trust/../../internal-api/admin`
would have been constructed via f-string — behaviour depends on httpx
URL handling.

## 7. Duplicate routes confirmed

```
GET /api/v1/files          → 401 (agent-compat mount)
GET /api/v1/storage/files  → 401 (primary mount)
```
Both reach the same handler. **GAP G16.**

## 8. Concurrency torture

### 8a. `POST /billing/allocate` — 100 parallel, same identity

```
$ seq 1 100 | xargs -I{} -P 20 curl ... /api/v1/billing/allocate \
     -d '{"windy_identity_id":"concurrent-race-1","tier":"pro"}'
100 × 200 OK
UserPlan rows for concurrent-race-1: 1   ✓ idempotent
```

### 8b. `POST /identity/link-passport` — 5 parallel, same identity, different passports

```
$ (for p in PP-A PP-B PP-C PP-D PP-E; do
     curl ... -d "{\"windy_identity_id\":\"race-link\",
                   \"passport_number\":\"$p\"}" &
   done; wait)
500 200 500 500 500
IdentityBridge rows for race-link: 1 (passport=PP-B)
```
**GAP G12.** 4 of 5 concurrent writes 500 with IntegrityError instead
of upsert-semantics.

## 9. Frozen-user access boundary

Via in-process test client (real route, real dep, seeded frozen
UserPlan + FileRecord):

```
GET  /api/v1/storage/files        → 200, lists 1 file           ← GAP G1
GET  /api/v1/storage/export       → 200, zip streams            ← GAP G1
GET  /api/v1/storage/files/{id}   → 404 (local-disk lookup
                                       mismatch in this probe)
                                    — the handler never short-
                                    circuited on frozen          ← GAP G1
POST /api/v1/storage/upload       → 403 frozen_account          ✓
```

The 404 in the download branch is an artefact of how the probe seeded
the blob vs how the provider expects its storage_key — the *handler*
code path reached the provider without ever consulting
`UserPlan.frozen`. A real blob would stream.
