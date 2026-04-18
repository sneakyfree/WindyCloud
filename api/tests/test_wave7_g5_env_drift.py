"""GAP G5: every Settings field must be represented in .env.example.

A new dev copying .env.example → .env should get a file that at least
names every config field, even if the value is intentionally blank.
Silent omissions (the Wave 2/3/4 regression) must not recur.
"""

from __future__ import annotations

from pathlib import Path

from api.app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def _env_example_keys() -> set[str]:
    keys: set[str] = set()
    for line in ENV_EXAMPLE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0].strip())
    return keys


def test_every_settings_field_is_in_env_example():
    documented = _env_example_keys()
    declared = {name.upper() for name in Settings.model_fields.keys()}
    missing = declared - documented
    assert not missing, (
        "Config fields declared on Settings but missing from .env.example: "
        f"{sorted(missing)}. Add entries so devs copying .env.example get "
        "a complete starting config."
    )


def test_env_example_does_not_reference_removed_fields():
    documented = _env_example_keys()
    declared = {name.upper() for name in Settings.model_fields.keys()}
    # Allow a narrow allowlist of non-Settings env vars (used by
    # docker-compose / CI shell but not by the app).
    allowed_extra = {"POSTGRES_PASSWORD"}
    stray = documented - declared - allowed_extra
    assert not stray, (
        "Variables in .env.example that are not on Settings and not in "
        f"the allowlist: {sorted(stray)}. Either add to Settings, add to "
        "the allowlist in this test, or remove from .env.example."
    )
