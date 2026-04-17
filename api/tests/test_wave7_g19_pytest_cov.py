"""GAP G19: pytest-cov is a declared dev dep and has a coverage floor.

Pre-G19 the project shipped no coverage tooling — `uv add coverage` was
needed just to get numbers. Now pytest-cov + coverage[toml] live in
pyproject [optional-dependencies.dev], and [tool.coverage.report] sets
a fail_under threshold so green-washed PRs can't silently regress.
"""

from __future__ import annotations

from pathlib import Path

import tomllib


REPO_ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    with (REPO_ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def test_pytest_cov_is_in_dev_deps():
    data = _pyproject()
    dev_deps = data["project"]["optional-dependencies"]["dev"]
    has_pytest_cov = any(d.startswith("pytest-cov") for d in dev_deps)
    assert has_pytest_cov, (
        "pytest-cov must be declared in [project.optional-dependencies.dev] "
        "so CI can run `uv run pytest --cov` without extra setup."
    )


def test_coverage_is_configured():
    data = _pyproject()
    assert "coverage" in data.get("tool", {}), (
        "[tool.coverage.run] / [tool.coverage.report] must exist in pyproject"
    )
    run = data["tool"]["coverage"]["run"]
    report = data["tool"]["coverage"]["report"]

    # Source pinned to api/app so migrations + test helpers don't
    # pollute the number.
    assert run.get("source") == ["api/app"]
    # Branch coverage on — catches untested error paths in auth / trust
    # code that statement-only reporting would miss.
    assert run.get("branch") is True
    # Fail-under exists and is low enough to not trip today's baseline
    # but high enough to block future regressions.
    fail_under = report.get("fail_under")
    assert isinstance(fail_under, int)
    assert 40 <= fail_under <= 70, (
        f"fail_under={fail_under} is outside the 40–70 sanity band"
    )


def test_omit_excludes_noise():
    """__version__ and migrations don't count toward coverage math."""
    data = _pyproject()
    omit = data["tool"]["coverage"]["run"].get("omit") or []
    assert any("__version__" in path for path in omit)
    assert any("migrations" in path for path in omit)
