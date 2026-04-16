# Windy Cloud — Production Environment Variables

This file enumerates the **shared secrets** Windy Cloud expects in production
and shows how to mint them safely. It does **not** contain real values — every
example below is a placeholder. Never commit `.env` to the repo.

---

## Required shared secrets

### `IDENTITY_WEBHOOK_SECRET`

**Purpose:** HMAC-SHA256 secret used to verify `POST /api/v1/webhooks/identity/created`.
Windy Pro (account-server) signs the webhook body with this secret; Windy
Cloud recomputes the signature and rejects mismatches with 403.

**Shared with:** `windy-pro` (account-server) — the *only* other holder.

**Length:** 32+ random bytes. Hex or URL-safe base64, caller's choice.

**Mint a new value:**
```bash
openssl rand -hex 32
# → 64-char hex, e.g. 00000000000000000000000000000000000000000000000000000000PLACEHOLDER
```
or:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**How to set:**
```bash
# On the cloud VPS
echo "IDENTITY_WEBHOOK_SECRET=<paste-value>" >> /etc/windy-cloud/.env
systemctl restart windy-cloud
```

**Rotation:** coordinate with windy-pro — update in both places during the same
maintenance window, otherwise the webhook will 403 and new signups won't
provision storage.

---

### `ETERNITAS_WEBHOOK_SECRET`

**Purpose:** HMAC fallback for `POST /api/v1/webhooks/passport/revoked`. The
*preferred* verification path is the ES256-signed token in the payload's
`token` field (validated against Eternitas JWKS) — this secret is reserved
for a future signed-body fallback so clients that can't JWT-sign still have
a supported path.

**Shared with:** `eternitas` — the *only* other holder.

**Length:** 32+ random bytes.

**Mint:**
```bash
openssl rand -hex 32
```

**Status:** reserved — not read by any code path today. Document now, wire
when Eternitas adds HMAC-body support.

---

### `SERVICE_TOKEN`

**Purpose:** Shared bearer for internal service-to-service calls that don't
carry a user JWT. Checked via `X-Service-Token` header with constant-time
compare.

**Used on:**
- `POST /api/v1/billing/allocate` (windy-agent hatch, account-server signups)
- `POST /api/v1/identity/link-passport`
- `GET  /api/v1/identity/by-passport/{passport}`
- `POST /api/v1/archive/{product}` — as an alternative to a user JWT, for
  product backends (windy-mail, windy-chat, windy-word, windy-clone,
  windy-agent) pushing archives on behalf of a user. Service callers also
  pass a `windy_identity_id` form field so Cloud knows which identity the
  upload belongs to.

**Shared with:** `windy-mail`, `windy-chat`, `windy-word` (windy-pro),
`windy-clone`, `windy-agent`. Cloud is the verifier; the others are presenters.

**Length:** 40+ random bytes.

**Mint:**
```bash
openssl rand -base64 48 | tr -d '='
# or
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**Rotation:** roll all six services together. Consider a dual-accept window
(read both `SERVICE_TOKEN` and `SERVICE_TOKEN_PREVIOUS`) if rolling without a
maintenance window becomes important.

---

## Eternitas URL (not a secret)

### `ETERNITAS_URL`

**Purpose:** Base URL of the Eternitas service used by the Trust API consumer
(`api/app/services/trust_client.py`). Cloud calls `GET {ETERNITAS_URL}/v1/trust/{passport}`
to look up per-passport trust tier + status, cached for 5 minutes.

**Example:**
```bash
ETERNITAS_URL=https://eternitas.ai
```

Separate from `ETERNITAS_JWKS_URL` (which is `{ETERNITAS_URL}/.well-known/eternitas-keys`).

---

## Example `.env` layout (placeholders only)

```bash
# Auth / JWKS
WINDY_PRO_JWKS_URL=https://windyword.ai/.well-known/jwks.json
ETERNITAS_JWKS_URL=https://eternitas.ai/.well-known/eternitas-keys
ETERNITAS_URL=https://eternitas.ai

# Shared secrets — mint per the instructions above
IDENTITY_WEBHOOK_SECRET=<openssl rand -hex 32>
ETERNITAS_WEBHOOK_SECRET=<openssl rand -hex 32>   # reserved
SERVICE_TOKEN=<openssl rand -base64 48 | tr -d =>

# Storage
R2_ACCOUNT_ID=<from cloudflare>
R2_ACCESS_KEY_ID=<from cloudflare>
R2_SECRET_ACCESS_KEY=<from cloudflare>
R2_BUCKET=windy-cloud-storage

# DB
DATABASE_URL=postgresql+asyncpg://...

# Monitoring
SENTRY_DSN=<from sentry>
```

---

## Verification

After deploy, confirm the secrets are wired without printing them:

```bash
# On the cloud VPS
sudo -u windy-cloud env | grep -E '^(IDENTITY_WEBHOOK_SECRET|SERVICE_TOKEN|ETERNITAS)' \
  | awk -F= '{print $1 "=[" length($2) " chars]"}'
```

Expected output (values masked):
```
ETERNITAS_JWKS_URL=[47 chars]
ETERNITAS_URL=[20 chars]
ETERNITAS_WEBHOOK_SECRET=[64 chars]
IDENTITY_WEBHOOK_SECRET=[64 chars]
SERVICE_TOKEN=[64 chars]
```

---

## Checklist for new deploys

- [ ] Mint `IDENTITY_WEBHOOK_SECRET`; copy the *same value* into windy-pro's env
- [ ] Mint `SERVICE_TOKEN`; copy into windy-mail, windy-chat, windy-word,
      windy-clone, windy-agent
- [ ] Set `ETERNITAS_URL` to the Eternitas base URL for this environment
      (staging vs prod)
- [ ] Restart cloud: `systemctl restart windy-cloud`
- [ ] Smoke-test: sign up a user via windy-pro; confirm a `UserPlan` row
      appears in cloud's DB
- [ ] Smoke-test: `curl -H "X-Service-Token: $SERVICE_TOKEN"
      $CLOUD/api/v1/identity/by-passport/EPT-0001`  →  200 or 404 (not 401)
