# Wave 7 — parked PRs

## [#4 — G10 gate init_db create_all on dev_mode](https://github.com/sneakyfree/WindyCloud/pull/4)

**Parked 2026-04-17 during the Wave 7 batch merge.**

**What failed.** Merged successfully (commit `627b24e`) but the
post-merge full integration suite regressed 11 unrelated tests with
order-dependent failures — `test_verify_identity_webhook_*`,
`test_verify_service_token_*`, `test_allocate_plan_unknown_tier_400`,
`test_migrate_accepts_valid_service_token`, all four `test_wave7_g21_*`
route-level checks, and `test_docs_exposed_when_dev_mode_true`. Main
has been reverted to `1e1ce5e`. Each failing test passes in isolation
via `pytest <path>::<name>`; the failure only surfaces when the full
suite runs with G10's tests earlier in the order.

**Root cause.** The G10 test file (`test_wave7_g10_init_db_gate.py`)
uses `importlib.reload(api.app.config)` and `importlib.reload(api.app.db.engine)`
to exercise the dev-mode branch. Module reload invalidates the
`settings` and `engine` references that 11 downstream tests captured
at collection time — those later tests then see stale module objects
with a different `_settings` instance and start failing in odd ways.
This is a test-hygiene bug, not a production-code bug: the G10
production change (gating `create_all` on `settings.dev_mode`) is
correct and doesn't regress anything when exercised without the
`importlib.reload` test scaffolding.

**What needs to change before re-merging.** Rewrite the test to not
reload modules. Options:
1. Parameterise `init_db` with an explicit `engine` argument and test
   the branch by passing a throwaway engine + a constructed settings
   object, instead of mutating module state.
2. Use pytest-asyncio's fresh-event-loop per test + `monkeypatch`
   on `engine.engine` / `engine.async_session` so module identity
   stays stable.
3. Move the behavioural check into an app-lifespan integration test
   that boots two app instances with different `DEV_MODE` env values
   in subprocesses, so module state is naturally fresh per process.

Option 1 is cleanest; budget ~30 min. Re-roll as its own PR when
someone picks this up — *not* a panic patch squeezed into another
merge.

**Grant's call (2026-04-17):** park for now, don't panic-patch in this
session. G10 is a prod-correctness fix (Alembic race), worth doing
right. The rest of Bucket B continues without it.

---

## [#10 — G7 optional JWT aud/iss validation](https://github.com/sneakyfree/WindyCloud/pull/10)

**Parked during the Wave 7 Bucket C batch merge.**

**What failed.** Merged successfully (commit `02c23f4`) but
post-merge the G5 drift test (`test_wave7_g5_env_drift.py::
test_every_settings_field_is_in_env_example`) caught that #10 added
three new `Settings` fields (`windy_cloud_expected_audience`,
`windy_pro_expected_issuer`, `eternitas_expected_issuer`) without
backfilling `.env.example`. Main reverted to `c66f99c`.

**Root cause.** Not a production-code bug — the G7 change is correct
and defaults-off. The miss is that G5's drift test (landed earlier in
this batch at `e1bd1db`) is the contract: any new `Settings` field
must appear in `.env.example`. #10 was written before the drift test
landed and didn't get updated on rebase.

**What needs to change before re-merging.** One commit on the
`wave-7-fix-g7-jwt-aud-iss` branch: add three lines to `.env.example`
under the `[Auth]` section:

```
# Optional audience / issuer enforcement (Wave 7 G7). Empty = off,
# matches pre-Wave-7 behaviour; set in prod once windy-pro + Eternitas
# agree on canonical aud / iss values.
WINDY_CLOUD_EXPECTED_AUDIENCE=
WINDY_PRO_EXPECTED_ISSUER=
ETERNITAS_EXPECTED_ISSUER=
```

Then force-push, rebase, re-merge. 5-minute fix, not a rewrite.

**Halt behaviour during this batch:** per Grant's "Halt on regression"
instruction for Bucket C, I stopped and surfaced rather than
continuing to #12/#15/#11/#19.
