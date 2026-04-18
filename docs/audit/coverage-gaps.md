# Coverage gaps — Wave 7 audit

Generated via `uv run coverage run --source=api/app -m pytest api/tests/
--ignore=api/tests/integration` (offline suite only — live integration
tests would push some of these higher).

Overall: **58%** (1377 / 2385 statements covered). Bar Grant cares about:
"auth / crypto / money / identity below 80% is a P0." Three files fail
that bar.

## Files below the 80% bar

| File | Coverage | Why it matters |
|---|---|---|
| `api/app/middleware/storage_warning.py` | **0%** | Middleware runs on every request; never exercised |
| `api/app/providers/r2.py` | **0%** | Production blob store — untested |
| `api/app/providers/aws_ec2.py` | **0%** | VPS provisioning |
| `api/app/providers/runpod.py` | **0%** | GPU compute |
| `api/app/providers/sagemaker.py` | **0%** | GPU compute |
| `api/app/routes/export.py` | 28% | GDPR export job |
| `api/app/routes/analytics.py` | 33% | Analytics endpoints |
| `api/app/routes/servers.py` | 38% | VPS CRUD |
| `api/app/auth/jwks.py` | **43%** | **AUTH — P1 (see GAP G7)** |
| `api/app/auth/webhook.py` | **43%** | **AUTH + FROZEN GATE — P1 (see GAP G1, G6)** |
| `api/app/routes/compute.py` | 45% | Money (cost_cents) |
| `api/app/auth/dependencies.py` | **47%** | **AUTH — P1** |
| `api/app/routes/sync.py` | 48% | Product sync |
| `api/app/routes/storage.py` | **49%** | **Blob storage — the primary product surface** |
| `api/app/routes/billing.py` | **54%** | **MONEY — P1 (see GAP G11)** |
| `api/app/db/engine.py` | 58% | Includes `init_db` race (G10) |
| `api/app/tasks/analytics.py` | 62% | |
| `api/app/providers/local_disk.py` | 64% | |
| `api/app/routes/archive.py` | 66% | Product archives |
| `api/app/services/trust_client.py` | **67%** | **TRUST — P1 (see GAP G8)** |
| `api/app/main.py` | 70% | App factory |
| `api/app/routes/webhooks.py` | 71% | Webhook handlers |

## Untested error paths (partial; from `coverage report -m`)

- `auth/jwks.py` — JWT validation retry + key-rotation path
- `auth/webhook.py` — `_raise_if_blocked` trust-API-unavailable branch
- `services/trust_client.py` — all non-200 response branches (429, 5xx,
  malformed JSON)
- `routes/billing.py` — `_estimate_storage_cost` tier transitions,
  `upgrade_plan` non-existent-plan branch
- `routes/webhooks.py` — `handle_passport_revoked` "token missing
  passport claim" + `handle_trust_changed` duplicate-delivery branch

## Mocked-instead-of-integration-tested areas

- `providers/r2.py` → tests run against `LocalDiskProvider`. R2's
  signing, multipart upload, and content-type round-trip are never
  exercised.
- Eternitas trust lookups — **live** tests exist at
  `api/tests/integration/test_trust_live*.py` and cover the happy
  path, but error scenarios (500, timeout, rate-limit) only exist as
  unit tests with in-memory stubs.
- No test exercises `handle_trust_changed` against a real signed
  delivery from Eternitas — only against locally-minted HMAC.

## Recommended targets

- `auth/*` → 85% minimum before launch.
- `services/trust_client.py` → 85% minimum.
- `routes/billing.py` → 85% minimum (focus on `allocate_plan` branches).
- `providers/r2.py` → at least 60% via botocore-stubs integration tests.
