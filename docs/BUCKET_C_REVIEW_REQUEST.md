# Wave 7 — Bucket C review requests

11 high-risk PRs held out of the batch-merge per
`docs/MERGE_TRIAGE.md`. Each touches auth, crypto, money, identity,
schema, or webhooks — the kind of code where a test-suite pass isn't
enough evidence of correctness. For each PR below: why it's high-risk,
what specifically needs a human eye, what a post-merge smoke should
cover.

---

## [#5 — G1 frozen users blocked on read/list/delete/export](https://github.com/sneakyfree/WindyCloud/pull/5)

**Why high-risk.** Auth/identity gate. Swaps `Depends(get_current_user)`
→ `Depends(require_not_frozen)` on eight previously-ungated routes:
list files, download by id, delete by id, usage, breakdown, export,
archive retrieve. This is a semantic change for every revoked user.
**Needs eyes on:** any product backend (windy-agent, windy-mail) that
was hitting these paths as a "system user" whose UserPlan might be
flagged frozen for unrelated reasons — that caller now 403s. Also:
confirm the list is complete (did we miss another read route?). **Smoke
after merge:** revoke a test passport via Eternitas, verify GET/DELETE
on its files return 403 `frozen_account`; un-revoke, verify they work
again.

## [#6 — G2 chunked bounded upload read](https://github.com/sneakyfree/WindyCloud/pull/6)

**Why high-risk.** Upload handler memory model rewrite — every upload
path now reads via `read_bounded()` in 1 MB chunks. Wrong enforcement
here silently OOMs pods or passes-through oversized payloads. **Needs
eyes on:** boundary semantics around exactly-limit-size uploads (does
`limit` bytes pass or fail?), behaviour on truncated uploads
(client disconnects mid-stream), and FastAPI's UploadFile spooling
interaction with our chunking. **Smoke after merge:** upload a file at
`max_upload_size - 1`, at `max_upload_size`, and at `max_upload_size + 1`
— expect 200, 200, 413.

## [#9 — G8 trust fail-closed on mutations](https://github.com/sneakyfree/WindyCloud/pull/9)

**Why high-risk.** Trust gating policy. Writes now 503 `trust_unavailable`
when Eternitas is unreachable; reads stay fail-open. Operationally
this means an Eternitas outage blocks all authenticated writes for
bot identities. **Needs eyes on:** the policy call itself — is "block
writes until trust recovers" the right default vs. "allow writes but
log warning"? Human-user writes aren't affected (they skip the trust
call entirely), so this is a bot-only constraint. **Smoke after merge:**
point `ETERNITAS_URL` at an unreachable host temporarily, verify bot
upload 503s and human upload 200s.

## [#10 — G7 optional JWT aud/iss validation](https://github.com/sneakyfree/WindyCloud/pull/10)

**Why high-risk.** JWT crypto settings. Ships **disabled by default**
(back-compat) so merging alone can't break auth. **Needs eyes on:** the
values to set in prod — Grant + windy-pro + Eternitas must agree on
canonical `aud` (\"windy-cloud\"?) and `iss` URLs before flipping the
env vars on. Merging now and setting env vars later is safe; no need
to block. **Smoke after merge:** nothing — mint a test token with and
without the configured `aud`; when env vars are empty, both accept;
when set, only matching `aud` accepts.

## [#11 — G6 Redis-backed trust cache + webhook dedup](https://github.com/sneakyfree/WindyCloud/pull/11)

**Why high-risk.** Auth-gating state moved fleet-wide. Prod behaviour
flips from per-worker to shared once `REDIS_URL` is set. **Needs eyes
on:** does a prod Redis instance exist with the right network
reachability from Fargate tasks? What happens when Redis fails over
(ElastiCache Multi-AZ) — we fail-soft but verify. **Smoke after merge:**
with `REDIS_URL` unset, dev still uses in-memory; with it set, a
`trust.changed` webhook landing on worker A flushes the cache worker B
reads. Roll 2+ Fargate tasks and confirm.

## [#12 — G12 link-passport concurrent upsert](https://github.com/sneakyfree/WindyCloud/pull/12)

**Why high-risk.** Schema + concurrency. Replaces SELECT→branch→INSERT
with dialect-aware `INSERT … ON CONFLICT DO UPDATE`. The SQLite path
is well-tested; the Postgres path is only compile-tested on the
branch. **Needs eyes on:** the Postgres `on_conflict_do_update` behaves
correctly with our unique-index structure on `windy_identity_id`, and
the optional-fields preservation (None means "don't overwrite") maps
cleanly to Postgres semantics. **Smoke after merge:** in staging Postgres,
run the adversarial probe from Wave 7 — 5 parallel link-passport calls
with same identity, different passports; expect 5 × 200 and one row.

## [#15 — G17+G18 tier vocabulary unification](https://github.com/sneakyfree/WindyCloud/pull/15)

**Why high-risk.** Money. Changes which plan names `/plan/upgrade`
accepts (drops `basic`, adds `max`) and bumps quota numbers across the
board. **Needs eyes on:** the placeholder prices (free/\$0, pro/\$5,
ultra/\$15, max/\$50) — pricing team must confirm or swap; existing
users with \`plan_id = \"basic\"\` in the DB keep working because we read
quota from the row, but cannot re-upgrade to \"basic\". Migration path
for any live basic users? **Smoke after merge:** query prod DB for any
\`UserPlan\` rows with \`plan_id = \"basic\"\` — if there are any, send a
migration notice and bulk-update them to \"free\" (same 5 GB quota).

## [#16 — G16 storage_router double-mount consolidation](https://github.com/sneakyfree/WindyCloud/pull/16)

**Why high-risk.** Identity-gate composition. Removes shadow endpoints
(\`/api/v1/upload\`, \`/files\`, \`/usage\`, \`/export\`, \`/breakdown\`,
\`/plans\`, \`/health\` mounted off-prefix) that **shouldn't** have callers
but might. **Needs eyes on:** windy-agent's ecosystem health probe is
the only caller I can find in-repo — confirm no external product
backend hits e.g. \`/api/v1/upload\` directly. **Smoke after merge:**
windy-agent CI health probe still green; \`curl /api/v1/upload\` returns
404.

## [#19 — G14 passport-revoked jti dedup](https://github.com/sneakyfree/WindyCloud/pull/19)

**Why high-risk.** Webhook. Now **requires** a \`jti\` claim on every
Eternitas revocation token. If Eternitas doesn't emit `jti`, all
revocation webhooks 400 and users stay un-frozen. **Needs eyes on:**
confirm Eternitas's current emitter sets \`jti\` on revocation tokens
(check \`emit_trust_changed\` path). **Smoke after merge:** trigger a
revocation via Eternitas, confirm the inbound token includes \`jti\` and
the replay test 200s once + 200-duplicate on retry.

## [#20 — G15 identity/created header rename](https://github.com/sneakyfree/WindyCloud/pull/20)

**Why high-risk.** Webhook header migration. New canonical
\`X-Pro-Signature\` + \`X-Pro-Timestamp\`; old \`X-Windy-Signature\` still
accepted during deprecation window. **Needs eyes on:** windy-pro's
current emitter — if it's already sending \`X-Pro-Signature\` we can
remove the legacy branch sooner; if it's still on \`X-Windy-Signature\`
the logs will show deprecation warnings until it migrates. **Smoke after
merge:** sign up a test user via windy-pro, verify identity/created
webhook reaches cloud and allocates a plan. Scan deploy logs for
"legacy X-Windy-Signature" lines — each is a windy-pro emitter that
still needs updating.

## [#24 — G20 per-route rate limits](https://github.com/sneakyfree/WindyCloud/pull/24)

**Why high-risk.** Rate-limit semantics change across every route.
Wrong limit tier on a hot route would page oncall at launch. **Needs
eyes on:** the caps themselves — 10/min on `/billing/allocate` is
meant for product backends fanning out new signups; is that tight
enough for a sign-up burst? 30/min on `/archive/*` — does a product's
nightly backup fit under that? Confirm with product leads. **Smoke after
merge:** fire 40 rapid `/storage/upload` calls from one caller; expect
30 × 200 + 10 × 429 with `Retry-After: 60`. Repeat for a different
caller (separate bucket) to confirm.

---

## Recommended review cadence

- **Same-day review:** #5 G1, #6 G2, #15 G17+G18 — these are the
  launch-blockers per the triage.
- **This-week review:** everything else — landing them before launch
  is ideal but not strictly required if the top 3 land.
- **Can defer to post-launch:** #10 G7 (back-compat-safe to merge,
  useless until env vars get set; Grant can flip those after launch).
