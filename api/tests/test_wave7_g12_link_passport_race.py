"""GAP G12: concurrent link-passport for the same identity must not 500.

Live adversarial probe in Wave 7 showed 4 of 5 parallel POSTs to
/api/v1/identity/link-passport with the same windy_identity_id (and
different passport_number values) returned 500 IntegrityError. The old
SELECT→branch→INSERT pattern raced because multiple coroutines saw
"no row", each tried to INSERT, and the unique-PK constraint rejected
four of them.

The fix replaces the pattern with a dialect-aware INSERT ... ON
CONFLICT DO UPDATE upsert. All concurrent callers now converge on the
same row, exactly one `passport_number` wins (last-writer in whatever
order the database settled), and nobody 500s.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.app.db.models import Base, IdentityBridge

TOKEN = "g12-svc-token"


@pytest.fixture
def service_token(monkeypatch):
    from api.app.config import settings

    monkeypatch.setattr(settings, "service_token", TOKEN)
    return TOKEN


@pytest.fixture
async def per_request_client():
    """Mimic production: every request gets its own AsyncSession from a
    shared engine, instead of sharing one session across coroutines.

    The conftest `client` fixture shares a single session for test
    convenience — fine for sequential tests, but masks concurrency races
    behind SQLAlchemy's single-session-per-flow rule. Here we need the
    real production-shape: N coroutines, N sessions, one engine / DB.
    """
    from api.app.db.engine import get_db
    from api.app.main import create_app

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _fresh_db():
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _fresh_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, factory

    await engine.dispose()


async def _link(client, identity: str, passport: str):
    return await client.post(
        "/api/v1/identity/link-passport",
        json={"windy_identity_id": identity, "passport_number": passport},
        headers={"X-Service-Token": TOKEN},
    )


@pytest.mark.asyncio
async def test_concurrent_same_identity_different_passports(per_request_client, service_token):
    """5 parallel link-passport calls, same identity, 5 different passports.

    Pre-G12: 1 × 200 + 4 × 500 (IntegrityError surfacing).
    Post-G12: 5 × 200, exactly one bridge row.
    """
    ac, factory = per_request_client
    passports = [f"ET-RACE-{i}" for i in range(5)]
    results = await asyncio.gather(*[_link(ac, "race-identity", p) for p in passports])

    status_codes = [r.status_code for r in results]
    assert all(sc == 200 for sc in status_codes), (
        f"Expected all 200 under concurrent upsert; got {status_codes} "
        f"with bodies: {[r.text[:200] for r in results if r.status_code != 200]}"
    )

    async with factory() as s:
        count = (
            await s.execute(
                select(func.count(IdentityBridge.windy_identity_id)).where(
                    IdentityBridge.windy_identity_id == "race-identity"
                )
            )
        ).scalar()
    assert count == 1, f"Expected exactly 1 bridge row, got {count}"


@pytest.mark.asyncio
async def test_concurrent_same_identity_same_passport_idempotent(per_request_client, service_token):
    """10 parallel calls with the same (identity, passport) — all 200, one row, same passport."""
    ac, factory = per_request_client
    results = await asyncio.gather(*[_link(ac, "idem-identity", "ET-IDEM-1") for _ in range(10)])
    assert all(r.status_code == 200 for r in results)

    async with factory() as s:
        row = (
            await s.execute(
                select(IdentityBridge).where(IdentityBridge.windy_identity_id == "idem-identity")
            )
        ).scalar_one()
    assert row.passport_number == "ET-IDEM-1"


@pytest.mark.asyncio
async def test_sequential_passport_change_still_updates(per_request_client, service_token):
    """Idempotency doesn't mean "immutable" — a later link call for the
    same identity with a *different* passport must update."""
    ac, factory = per_request_client
    r1 = await _link(ac, "mutable-identity", "ET-FIRST")
    r2 = await _link(ac, "mutable-identity", "ET-SECOND")
    assert r1.status_code == 200
    assert r2.status_code == 200

    async with factory() as s:
        row = (
            await s.execute(
                select(IdentityBridge).where(IdentityBridge.windy_identity_id == "mutable-identity")
            )
        ).scalar_one()
    assert row.passport_number == "ET-SECOND"


@pytest.mark.asyncio
async def test_link_passport_preserves_optional_fields_across_upsert(
    per_request_client, service_token
):
    """operator_email + linked_by should be preserved when a later call
    doesn't provide them (None means 'don't overwrite')."""
    ac, factory = per_request_client
    r1 = await ac.post(
        "/api/v1/identity/link-passport",
        json={
            "windy_identity_id": "preserve-identity",
            "passport_number": "ET-PRES",
            "operator_email": "ops@example.com",
            "linked_by": "initial",
        },
        headers={"X-Service-Token": TOKEN},
    )
    assert r1.status_code == 200

    # Second call updates only the passport; operator_email should NOT wipe.
    r2 = await _link(ac, "preserve-identity", "ET-PRES-2")
    assert r2.status_code == 200

    async with factory() as s:
        row = (
            await s.execute(
                select(IdentityBridge).where(
                    IdentityBridge.windy_identity_id == "preserve-identity"
                )
            )
        ).scalar_one()
    assert row.passport_number == "ET-PRES-2"
    assert row.operator_email == "ops@example.com", (
        "operator_email should be preserved when the later call passes None"
    )
    assert row.linked_by == "initial"
