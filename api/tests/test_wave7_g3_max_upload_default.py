"""GAP G3: max_upload_size default must stay under Fargate task memory.

A 1 GB default against a 1 GB task memory allocation is one OOM away
from a worker restart. We pin the default at 256 MB so even a pre-WAF
request can't blow the pod, and we require a 4× headroom invariant
relative to the CLOUD_DEPLOYMENT.md provisioned task memory (1024 MB).
"""

from __future__ import annotations

from api.app.config import Settings

# CLOUD_DEPLOYMENT.md §5.2 provisions 1024 MB task memory.
FARGATE_TASK_MEMORY_BYTES = 1024 * 1024 * 1024
REQUIRED_HEADROOM_RATIO = 4


def test_default_max_upload_size_fits_in_fargate_task():
    s = Settings(_env_file=None)
    # 4× headroom: max_upload_size * 4 ≤ task memory
    assert s.max_upload_size * REQUIRED_HEADROOM_RATIO <= FARGATE_TASK_MEMORY_BYTES, (
        f"max_upload_size={s.max_upload_size} is too large for Fargate's "
        f"{FARGATE_TASK_MEMORY_BYTES} B task memory (need {REQUIRED_HEADROOM_RATIO}× headroom). "
        "Either drop the default or bump the task memory in CLOUD_DEPLOYMENT.md."
    )


def test_default_max_upload_size_is_256_MB():
    s = Settings(_env_file=None)
    assert s.max_upload_size == 268_435_456, (
        f"Expected 256 MB (268_435_456), got {s.max_upload_size}. "
        "Coordinate any bump with CLOUD_DEPLOYMENT.md task sizing."
    )


def test_env_override_still_works():
    """MAX_UPLOAD_SIZE env var still changes the ceiling."""
    s = Settings(_env_file=None, max_upload_size=10_000_000)
    assert s.max_upload_size == 10_000_000
