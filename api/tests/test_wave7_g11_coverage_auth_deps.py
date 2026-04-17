"""G11 coverage push — auth/dependencies.py get_current_user paths.

Baseline 47%. This targets the missing 39-67 range — the JWT fallback
(Pro → Eternitas), the exception branches, and the 401 no-validator
path.
"""

from __future__ import annotations

import pytest
from fastapi.security import HTTPAuthorizationCredentials

import jwt as pyjwt


@pytest.mark.asyncio
async def test_get_current_user_pro_happy(monkeypatch):
    from api.app.auth import dependencies as deps_mod
    from api.app.auth import jwks as jwks_mod

    class _ProStub:
        def validate_token(self, token):
            return {
                "sub": "user-pro",
                "windy_identity_id": "user-pro",
                "exp": 9999999999,
            }

    monkeypatch.setattr(deps_mod, "get_pro_validator", lambda: _ProStub())

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="t")
    user = await deps_mod.get_current_user(creds)
    assert user.identity_id == "user-pro"
    assert user.source == "windy_pro"


@pytest.mark.asyncio
async def test_get_current_user_falls_back_to_eternitas(monkeypatch):
    """Pro rejects → Eternitas accepts → success via the fallback branch."""
    from api.app.auth import dependencies as deps_mod
    from api.app.auth import jwks as jwks_mod

    class _ProRejects:
        def validate_token(self, token):
            raise pyjwt.InvalidTokenError("not Pro's token")

    class _EternitasAccepts:
        def validate_token(self, token):
            return {
                "sub": "EPT-bot-1",
                "passport_number": "ET-BOT-1",
                "exp": 9999999999,
            }

    monkeypatch.setattr(deps_mod, "get_pro_validator", lambda: _ProRejects())
    monkeypatch.setattr(deps_mod, "get_eternitas_validator", lambda: _EternitasAccepts())

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="t")
    user = await deps_mod.get_current_user(creds)
    assert user.identity_id == "ET-BOT-1"
    assert user.source == "eternitas"


@pytest.mark.asyncio
async def test_get_current_user_401_when_both_validators_reject(monkeypatch):
    from fastapi import HTTPException

    from api.app.auth import dependencies as deps_mod
    from api.app.auth import jwks as jwks_mod

    class _Rejects:
        def validate_token(self, token):
            raise pyjwt.InvalidTokenError("nope")

    monkeypatch.setattr(deps_mod, "get_pro_validator", lambda: _Rejects())
    monkeypatch.setattr(deps_mod, "get_eternitas_validator", lambda: _Rejects())

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="garbage")
    with pytest.raises(HTTPException) as exc:
        await deps_mod.get_current_user(creds)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_catches_unexpected_error_and_continues(monkeypatch):
    """If one validator raises an unexpected (non-JWT) error, the
    handler logs + moves on to the next validator, not 500."""
    from fastapi import HTTPException

    from api.app.auth import dependencies as deps_mod
    from api.app.auth import jwks as jwks_mod

    class _Explodes:
        def validate_token(self, token):
            raise RuntimeError("unexpected pro failure")

    class _Explodes2:
        def validate_token(self, token):
            raise RuntimeError("unexpected eternitas failure")

    monkeypatch.setattr(deps_mod, "get_pro_validator", lambda: _Explodes())
    monkeypatch.setattr(deps_mod, "get_eternitas_validator", lambda: _Explodes2())

    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="anything")
    with pytest.raises(HTTPException) as exc:
        await deps_mod.get_current_user(creds)
    assert exc.value.status_code == 401
