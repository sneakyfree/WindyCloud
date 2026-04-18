# Wave 7 PR Merge Triage

*Generated 2026-04-17.* 27 open PRs from Wave 7. Bucketed for batch-merge,
with the three that would cause the most user pain at launch called out
at the bottom.

**Cumulative diff: +6,983 additions / −385 deletions across 27 PRs.**

---

## Bucket A — MERGE NOW (4 PRs)

Pure docs / tests / dev-tool config. No runtime behaviour changes. Land any time.

- [**#1**](https://github.com/sneakyfree/WindyCloud/pull/1) — GAP_ANALYSIS inventory. Docs-only; the source of truth for the rest of the triage.
- [**#18**](https://github.com/sneakyfree/WindyCloud/pull/18) — G19 pytest-cov dev dep + `fail_under=50`. Pure tool-config; doesn't touch runtime code.
- [**#22**](https://github.com/sneakyfree/WindyCloud/pull/22) — G11 auth + trust coverage push. 48 new tests; adds zero production code. Takes auth/jwks + dependencies from 43% / 47% to 100%.
- [**#27**](https://github.com/sneakyfree/WindyCloud/pull/27) — G25+G27+G29+G30 doc sweep. Docstrings + README + drift-test. Nothing executes differently; the drift test just makes future README misses loud.

---

## Bucket B — SAFE WITH SMOKE (12 PRs)

Real behaviour change, but small blast radius, well-tested, trivially reversible. One smoke check each after deploy.

- [**#2**](https://github.com/sneakyfree/WindyCloud/pull/2) — G9 hide `/docs` in prod. Dev-mode-gated; prod `/docs` returns 404 post-merge. Smoke: `curl $CLOUD/docs` returns 404 in prod, 200 in dev.
- [**#3**](https://github.com/sneakyfree/WindyCloud/pull/3) — G5 `.env.example` backfill + drift test. Doc-only effect at runtime; the test blocks future field drift. Smoke: none needed.
- [**#4**](https://github.com/sneakyfree/WindyCloud/pull/4) — G10 don't race Alembic (dev_mode gate on `init_db.create_all`). Prod: no more startup table creation. Smoke: confirm `alembic upgrade head` task runs before API task set.
- [**#7**](https://github.com/sneakyfree/WindyCloud/pull/7) — G4 r2_bucket fail-fast. Partial R2 config now raises at startup instead of silently hitting a wrong bucket. Smoke: pod fails to boot with missing `R2_BUCKET`; fix config; pod boots.
- [**#8**](https://github.com/sneakyfree/WindyCloud/pull/8) — G3 max_upload_size default 1 GB → 256 MB. 256 MB+ uploads now 413. Smoke: upload 200 MB (OK), upload 300 MB (413).
- [**#13**](https://github.com/sneakyfree/WindyCloud/pull/13) — G21 passport format validation. New 400s on malformed passports; all Eternitas seed formats still accepted. Smoke: allocate with `ET26-TEST-EXCP` succeeds; allocate with `../../foo` 422s.
- [**#14**](https://github.com/sneakyfree/WindyCloud/pull/14) — G24 CORS hardening. Explicit methods + headers instead of wildcards. Smoke: open dashboard, confirm authed JMAP/fetch calls still work.
- [**#17**](https://github.com/sneakyfree/WindyCloud/pull/17) — G13 archive_migrate service-token auth. Breaking for any JWT caller (there shouldn't be one; it's product-to-cloud). Smoke: product backend call with `X-Service-Token` returns 200.
- [**#21**](https://github.com/sneakyfree/WindyCloud/pull/21) — G23 crash-safe webhook wrapper. Unhandled exceptions now return 200 `accepted_with_error` instead of 500. Smoke: check Sentry still catches the underlying error.
- [**#23**](https://github.com/sneakyfree/WindyCloud/pull/23) — G22 trust cache warmup. New startup task pre-fetches trust for bridge rows. Smoke: startup log shows `trust-warmup: pre-fetched N/N passports`.
- [**#25**](https://github.com/sneakyfree/WindyCloud/pull/25) — G31+G33 `/health` minimal + startup-task Sentry. `/health` no longer leaks provider names. Smoke: internal `/health/full` still exposes the detail; retention failure triggers a Sentry event.
- [**#26**](https://github.com/sneakyfree/WindyCloud/pull/26) — compute `/stt` frozen gate (re-graded P3 → P1). Frozen users now 403 on `/compute/stt` same as `/storage/upload`. Smoke: revoke test passport, confirm STT 403s.

---

## Bucket C — HIGH RISK (11 PRs)

Touches auth / crypto / money / identity / schema / webhooks. Each needs a real reviewer before merge.

- [**#5**](https://github.com/sneakyfree/WindyCloud/pull/5) — G1 frozen read/list/delete/export gate. **Auth/identity.** Largest surface change. 8 previously-ungated routes now enforce `require_not_frozen`. Reviewer focus: does every route that should gate actually gate? Any legit product backend that was hitting these as a frozen "system user"?
- [**#6**](https://github.com/sneakyfree/WindyCloud/pull/6) — G2 chunked bounded upload read. **Upload handler rewrite.** Changes the memory model for every upload. Reviewer focus: no behaviour regression on small uploads; 413 fires exactly at the boundary.
- [**#9**](https://github.com/sneakyfree/WindyCloud/pull/9) — G8 trust fail-closed on mutations. **Auth/trust.** Writes now 503 when Eternitas is unreachable. Reviewer focus: do we want fail-closed on every write, or only on destructive ones?
- [**#10**](https://github.com/sneakyfree/WindyCloud/pull/10) — G7 optional JWT aud/iss. **Crypto.** Back-compat (defaults off). Needs Grant + windy-pro to agree on the `aud` value before turning on.
- [**#11**](https://github.com/sneakyfree/WindyCloud/pull/11) — G6 Redis trust cache + webhook dedup. **Auth gating state.** Fleet-wide semantics change. Reviewer focus: Redis outage path fails soft (proven in tests); confirm Redis instance exists in prod.
- [**#12**](https://github.com/sneakyfree/WindyCloud/pull/12) — G12 link-passport upsert. **Schema + concurrency.** Dialect-aware INSERT…ON CONFLICT. Reviewer focus: verify the Postgres path on staging before prod; SQLite path already covered by tests.
- [**#15**](https://github.com/sneakyfree/WindyCloud/pull/15) — G17+G18 tier vocabulary unification. **Money.** Changes which plan names `/plan/upgrade` accepts + the quota numbers. Reviewer focus: confirm prices are intentional; no existing "basic"-plan users in the DB that would break.
- [**#16**](https://github.com/sneakyfree/WindyCloud/pull/16) — G16 storage_router double-mount consolidation. **Identity gate composition.** Removes shadow endpoints windy-agent's ecosystem-health probe calls. Reviewer focus: confirm windy-agent still sees `/api/v1/files` OK; nothing else was depending on the shadow paths.
- [**#19**](https://github.com/sneakyfree/WindyCloud/pull/19) — G14 passport-revoked jti dedup. **Webhook.** Now requires `jti` on Eternitas revocation tokens. Needs Eternitas to mint `jti` — already true in their current emitter, but confirm before merge.
- [**#20**](https://github.com/sneakyfree/WindyCloud/pull/20) — G15 identity/created header rename. **Webhook.** New `X-Pro-Signature` header; old `X-Windy-Signature` still accepted during deprecation window. Coordinates with windy-pro to migrate.
- [**#24**](https://github.com/sneakyfree/WindyCloud/pull/24) — G20 per-route rate limits. **Rate-limit logic.** Changes the shape of the limiter. Reviewer focus: verify legitimate product-backend bursts don't trip the new tighter caps.

---

## Bucket D — BLOCKED ON GRANT (0 PRs)

Nothing in the queue is strictly blocked. The closest is **#10 G7** — back-compat-safe to merge but needs coordination with windy-pro before the `aud` / `iss` env vars get set to non-empty values in prod. Tracked under Bucket C.

---

## Bucket E — DEFER (0 PRs)

No P3s in the open-PR queue. The six P3 items in `GAP_ANALYSIS.md` are still unshipped but none have PRs — they're maintenance-mode polish that doesn't justify dedicated review cycles.

---

## TOP 3 MUST-MERGE BEFORE LAUNCH

1. [**#5 — G1 frozen users blocked on read/list/delete/export**](https://github.com/sneakyfree/WindyCloud/pull/5)
   *Without it:* revocation is cosmetic. A revoked user still lists, downloads, zips-exports, and deletes their own data. Compliance / legal-hold features are unenforceable. The whole passport-revoked webhook contract becomes theatrical.

2. [**#6 — G2 chunked bounded upload read**](https://github.com/sneakyfree/WindyCloud/pull/6)
   *Without it:* one upload at the default ceiling buffers a gigabyte of Python bytes on a 1 GB Fargate task and OOM-kills the worker. Any authenticated user can DoS a pod on demand. This is the front-door foot-gun.

3. [**#15 — G17+G18 tier vocabulary unification**](https://github.com/sneakyfree/WindyCloud/pull/15)
   *Without it:* `POST /billing/plan/upgrade {"plan_id": "max"}` returns 400 because the billing endpoint still uses the old `free/basic/pro/ultra` vocab while the allocator and dashboards use `free/pro/ultra/max`. Users hitting the upgrade UI to get the highest tier see a billing UX wall on day 1. Quota numbers also disagree across surfaces — a user on "free" could see 500 MB in one place and 5 GB in another.

---

## Bucket counts (sanity)

| Bucket | Count |
|---|---:|
| A — MERGE NOW | 4 |
| B — SAFE WITH SMOKE | 12 |
| C — HIGH RISK | 11 |
| D — BLOCKED ON GRANT | 0 |
| E — DEFER | 0 |
| **Total** | **27** |
