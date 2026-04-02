# Windy Cloud — Integration Guide

How each Windy product integrates with Cloud.

---

## Auth — All Products

Every request to Windy Cloud requires a Bearer JWT.

**User requests:** JWT from Windy Pro login (RS256). Cloud validates via JWKS at `WINDY_PRO_JWKS_URL`. Extract `windy_identity_id` from claims.

**Agent requests:** EPT token from Eternitas (ES256). Cloud validates via JWKS at `ETERNITAS_JWKS_URL`. Extract `passport_id` from claims, map to `windy_identity_id` via owner lookup.

**Service-to-service:** JWT from Pro's `client_credentials` grant. Same JWKS validation.

---

## Windy Fly (Agent)

**Existing client:** `src/windyfly/integrations/windy_cloud.py`

The agent already calls:
- `POST /api/storage/files/upload` — multipart upload with `file` + `metadata` fields
- `GET /api/storage/health` — availability check

The client uses `WINDY_CLOUD_URL` env var and Bearer JWT auth. Supports optional `encryption_key` for encrypted uploads.

**What Cloud must serve:**
```
POST /api/v1/storage/upload     ← agent database backup
GET  /api/v1/storage/health     ← health check
```

**Archive payload:** Agent sends its SQLite database as a file with metadata:
```json
{
  "product": "windy_fly",
  "type": "agent_backup",
  "agent_name": "Aria",
  "passport_id": "EPT-XXXX"
}
```

---

## Windy Pro (Recordings, Files)

**Current state:** Pro has its own R2 adapter in `account-server/src/services/r2-adapter.ts` storing in bucket `windypro-storage` with path `users/{userId}/{type}/{filename}`.

**Migration plan:**
1. Phase 1: Cloud uses separate bucket `windy-cloud-storage`. Pro keeps its bucket.
2. Phase 2: Pro's upload routes write to Cloud API instead of R2 directly.
3. Phase 3: Migrate existing files.

**Archive payload:** Recordings, transcriptions, translations:
```json
{
  "product": "windy_pro",
  "type": "recording",
  "duration": 120,
  "format": "opus"
}
```

---

## Windy Chat (Encrypted Backups)

**Current state:** Chat backup service at port 8104 creates AES-256-GCM encrypted backups and stores in R2.

**Encryption format:** `salt(32) + iv(12) + authTag(16) + ciphertext` — PBKDF2 with 100K iterations.

**Integration:** Cloud stores encrypted blobs as-is. **Do not re-encrypt.** Chat handles encryption, Cloud just stores.

**Archive payload:**
```json
{
  "product": "windy_chat",
  "type": "chat_backup",
  "encrypted": true,
  "retention_count": 7
}
```

Cloud enforces retention (keep last N backups per product per identity).

---

## Windy Mail (Server Backups)

**Current state:** Bash scripts (`backup-postgres.sh`, `backup-stalwart.sh`) use rclone to push to R2. 90-day daily retention, 12-month weekly retention.

**Migration:** Eventually scripts call Cloud's archive API. For now, coexist.

**Archive payload:**
```json
{
  "product": "windy_mail",
  "type": "postgres_backup",
  "retention_days": 90
}
```

---

## Windy Code (Settings Sync)

**Future integration:** Sync IDE settings, keybindings, extensions list across devices.

**Archive payload:**
```json
{
  "product": "windy_code",
  "type": "settings",
  "sync": true
}
```

Settings sync is real-time (not just archive) — requires a sync protocol. Phase 2+.

---

## Windy Mobile (Recording Sync)

**Current state:** Mobile syncs recordings to Pro via `POST /api/v1/recordings/sync`.

**Migration:** Mobile syncs to Cloud, Pro reads from Cloud. Eliminates direct mobile→Pro sync.

---

## Eternitas (Soul Key Backup)

**Sensitive:** Soul Keys are encrypted with Fernet using server's SECRET_KEY.

**Archive payload:** Only the encrypted vault blob, never raw keys.
```json
{
  "product": "eternitas",
  "type": "soul_vault_backup",
  "encrypted": true
}
```

Cloud stores this as opaque encrypted data. Zero-knowledge.

---

## Cloud STT — Compute Integration

Any product can call Cloud STT:

```
POST /api/v1/compute/stt
Content-Type: multipart/form-data
Authorization: Bearer <jwt>

file: <audio_file>
language: en  (optional)
model: large-v3  (optional)
```

Response:
```json
{
  "job_id": "stt-xxxxx",
  "status": "completed",
  "text": "Hello world",
  "segments": [...],
  "duration_seconds": 12.5,
  "cost_cents": 4
}
```

For long files, returns `status: "processing"` and the client polls `GET /api/v1/compute/stt/{job_id}`.
