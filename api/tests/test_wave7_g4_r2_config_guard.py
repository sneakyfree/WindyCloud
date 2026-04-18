"""GAP G4: R2 misconfiguration must fail fast at startup.

The old default `r2_bucket = "windy-cloud-storage"` meant a production
deploy with R2 creds but no explicit bucket silently hit a bucket name
that didn't exist in the prod account. Every upload then 502'd — a
cliff we only noticed after the first user complaint.

This test pins down the new behavior:
  - All four R2 vars set       → r2_configured = True, no reason
  - All four R2 vars unset     → r2_configured = False, no reason (local disk)
  - Any partial combination    → reason = "<specific missing vars>"
"""

from __future__ import annotations

import pytest

from api.app.config import Settings


def _s(**overrides) -> Settings:
    """Build a Settings with overrides, ignoring any .env file."""
    return Settings(_env_file=None, **overrides)


def test_fully_unset_falls_back_to_local_disk():
    s = _s(
        r2_account_id="",
        r2_access_key_id="",
        r2_secret_access_key="",
        r2_bucket="",
    )
    assert s.r2_configured is False
    assert s.r2_misconfiguration_reason is None


def test_fully_set_is_configured():
    s = _s(
        r2_account_id="acc",
        r2_access_key_id="ak",
        r2_secret_access_key="sk",
        r2_bucket="bkt",
    )
    assert s.r2_configured is True
    assert s.r2_misconfiguration_reason is None


@pytest.mark.parametrize(
    "overrides,expect_missing",
    [
        (
            {"r2_account_id": "acc", "r2_access_key_id": "ak", "r2_secret_access_key": "sk"},
            "R2_BUCKET",
        ),
        (
            {"r2_account_id": "acc", "r2_access_key_id": "ak", "r2_bucket": "bkt"},
            "R2_SECRET_ACCESS_KEY",
        ),
        (
            {"r2_account_id": "acc", "r2_bucket": "bkt"},
            "R2_ACCESS_KEY_ID",
        ),
        (
            {"r2_bucket": "bkt"},
            "R2_ACCOUNT_ID",
        ),
    ],
)
def test_partial_config_reports_specific_missing_vars(overrides, expect_missing):
    base = {
        "r2_account_id": "",
        "r2_access_key_id": "",
        "r2_secret_access_key": "",
        "r2_bucket": "",
    }
    base.update(overrides)
    s = _s(**base)
    assert s.r2_configured is False
    reason = s.r2_misconfiguration_reason
    assert reason is not None, f"expected a reason for {overrides}"
    assert expect_missing in reason


def test_default_bucket_no_longer_present():
    """The old default was 'windy-cloud-storage' which drifted from the
    prod bucket 'windy-cloud-storage-prod'. Default must now be empty."""
    s = _s()
    assert s.r2_bucket == "", (
        f"r2_bucket must default to '' so partial configs are caught; was {s.r2_bucket!r}"
    )
