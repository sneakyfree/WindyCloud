"""Wave 14 P3 — /archive/* honours an explicit `filename` form field.

Smoke report §5 flagged that posting
    -F "file=@cc_a.txt" -F "filename=chat-backup.txt"
to /archive/chat stored under the multipart filename `cc_a.txt` (the
`filename` form field was silently ignored — the route didn't declare
it). Retrieve at /archive/retrieve/windy_chat/chat-backup.txt then 404-d.

Wave 14 P3 adds a `filename: str | None = Form(None)` parameter to each
archive route. When present, it wins; otherwise we fall back to
file.filename, then to a uuid-stamped default.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_archive_chat_honours_explicit_filename_form_field(client):
    """POST with `filename=X` → retrieve at /archive/retrieve/windy_chat/X."""
    resp = await client.post(
        "/api/v1/archive/chat",
        files={"file": ("multipart-name.txt", b"hello", "text/plain")},
        data={"filename": "renamed-backup.txt", "metadata": "{}"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200, resp.text
    stored = resp.json()
    # storage key uses the server-side filename, so the key path should
    # contain the override.
    assert "renamed-backup.txt" in stored["key"]

    retrieve = await client.get(
        "/api/v1/archive/retrieve/windy_chat/renamed-backup.txt",
        headers={"Authorization": "Bearer fake"},
    )
    assert retrieve.status_code == 200
    assert retrieve.content == b"hello"

    # The multipart name should NOT find the file anymore.
    miss = await client.get(
        "/api/v1/archive/retrieve/windy_chat/multipart-name.txt",
        headers={"Authorization": "Bearer fake"},
    )
    assert miss.status_code == 404


@pytest.mark.asyncio
async def test_archive_falls_back_to_multipart_filename_when_form_absent(client):
    """Pre-Wave-14 behaviour: no `filename` → use multipart filename."""
    resp = await client.post(
        "/api/v1/archive/chat",
        files={"file": ("cc_a.txt", b"world", "text/plain")},
        data={"metadata": "{}"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert "cc_a.txt" in resp.json()["key"]

    retrieve = await client.get(
        "/api/v1/archive/retrieve/windy_chat/cc_a.txt",
        headers={"Authorization": "Bearer fake"},
    )
    assert retrieve.status_code == 200


@pytest.mark.asyncio
async def test_archive_mail_honours_filename(client):
    """Regression: covers the mail archive route too."""
    resp = await client.post(
        "/api/v1/archive/mail",
        files={"file": ("raw.eml", b"body", "message/rfc822")},
        data={"filename": "2026-04-inbox.eml", "metadata": "{}"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert "2026-04-inbox.eml" in resp.json()["key"]


@pytest.mark.asyncio
async def test_archive_empty_filename_falls_back(client):
    """An explicit empty `filename=` form value shouldn't override — we
    treat that as "not supplied" because _sanitize_filename would then
    produce a uuid default and the caller almost certainly didn't mean
    that."""
    resp = await client.post(
        "/api/v1/archive/chat",
        files={"file": ("real-name.txt", b"x", "text/plain")},
        data={"filename": "", "metadata": "{}"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    # Expected behaviour: the empty `filename=` form field is falsy, so
    # we fall back to the multipart name.
    assert "real-name.txt" in resp.json()["key"]


@pytest.mark.asyncio
async def test_archive_filename_sanitised(client):
    """Path-traversal attempts via the override are still sanitised."""
    resp = await client.post(
        "/api/v1/archive/chat",
        files={"file": ("ok.txt", b"x", "text/plain")},
        data={"filename": "../../etc/passwd", "metadata": "{}"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    # _sanitize_filename strips path separators + collapses dots.
    key = resp.json()["key"]
    assert "../" not in key
    assert "/etc/" not in key
