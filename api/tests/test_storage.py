"""Storage CRUD tests."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_upload_and_list(client):
    """Upload a file, then verify it appears in the file list."""
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("test.txt", b"hello world", "text/plain")},
        data={"product": "windy_pro", "file_type": "recording"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["size"] == 11
    file_id = body["file_id"]

    # List files
    resp = await client.get(
        "/api/v1/storage/files",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    files = resp.json()["files"]
    assert len(files) == 1
    assert files[0]["file_id"] == file_id
    assert files[0]["product"] == "windy_pro"


@pytest.mark.asyncio
async def test_upload_download_delete(client):
    """Full lifecycle: upload → download → delete."""
    # Upload
    content = b"binary data here"
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("data.bin", content, "application/octet-stream")},
        data={"product": "general", "file_type": "file"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    file_id = resp.json()["file_id"]

    # Download
    resp = await client.get(
        f"/api/v1/storage/files/{file_id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.content == content

    # Delete
    resp = await client.delete(
        f"/api/v1/storage/files/{file_id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    # Verify gone
    resp = await client.get(
        f"/api/v1/storage/files/{file_id}",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_usage_endpoint(client):
    """Usage should reflect uploaded file sizes."""
    resp = await client.get(
        "/api/v1/storage/usage",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    usage = resp.json()
    assert usage["used_bytes"] == 0
    assert usage["quota_bytes"] == 524_288_000

    # Upload a file
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("f.txt", b"x" * 100, "text/plain")},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.get(
        "/api/v1/storage/usage",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.json()["used_bytes"] == 100


@pytest.mark.asyncio
async def test_file_list_pagination(client):
    """Pagination should work with limit and offset."""
    for i in range(5):
        await client.post(
            "/api/v1/storage/upload",
            files={"file": (f"file{i}.txt", f"data{i}".encode(), "text/plain")},
            headers={"Authorization": "Bearer fake"},
        )

    resp = await client.get(
        "/api/v1/storage/files?limit=2&offset=0",
        headers={"Authorization": "Bearer fake"},
    )
    body = resp.json()
    assert len(body["files"]) == 2
    assert body["truncated"] is True
    assert body["total"] == 5


@pytest.mark.asyncio
async def test_file_list_filter_by_product(client):
    """Filter files by product."""
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("a.txt", b"a", "text/plain")},
        data={"product": "windy_pro"},
        headers={"Authorization": "Bearer fake"},
    )
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("b.txt", b"b", "text/plain")},
        data={"product": "windy_chat"},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.get(
        "/api/v1/storage/files?product=windy_pro",
        headers={"Authorization": "Bearer fake"},
    )
    assert len(resp.json()["files"]) == 1
    assert resp.json()["files"][0]["product"] == "windy_pro"


@pytest.mark.asyncio
async def test_storage_health(client):
    """Storage health should report the provider."""
    resp = await client.get("/api/v1/storage/health", headers={"Authorization": "Bearer fake"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["provider"] == "LocalDiskProvider"


@pytest.mark.asyncio
async def test_storage_plans_no_auth(client):
    """Plans endpoint should be public (no auth required)."""
    resp = await client.get("/api/v1/storage/plans")
    assert resp.status_code == 200
    plans = resp.json()["plans"]
    assert len(plans) == 4
    assert plans[0]["plan_id"] == "free"
    assert plans[0]["price_cents_per_month"] == 0
    assert plans[1]["plan_id"] == "basic"
    assert plans[1]["price_display"] == "$2/mo"
    assert plans[2]["plan_id"] == "pro"
    assert plans[3]["plan_id"] == "ultra"
    assert plans[3]["storage_display"] == "200 GB"


@pytest.mark.asyncio
async def test_storage_breakdown(client):
    """Breakdown returns per-product usage."""
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("a.txt", b"aaa", "text/plain")},
        data={"product": "windy_chat"},
        headers={"Authorization": "Bearer fake"},
    )
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("b.txt", b"bbbbb", "text/plain")},
        data={"product": "windy_pro"},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.get(
        "/api/v1/storage/breakdown",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    products = resp.json()["products"]
    assert len(products) == 2
    by_product = {p["product"]: p for p in products}
    assert by_product["windy_chat"]["bytes"] == 3
    assert by_product["windy_pro"]["bytes"] == 5


@pytest.mark.asyncio
async def test_data_export(client):
    """Export returns a ZIP with uploaded files."""
    await client.post(
        "/api/v1/storage/upload",
        files={"file": ("test.txt", b"export-me", "text/plain")},
        data={"product": "general"},
        headers={"Authorization": "Bearer fake"},
    )

    resp = await client.get(
        "/api/v1/storage/export",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert len(resp.content) > 0


@pytest.mark.asyncio
async def test_data_export_empty(client):
    """Export with no files returns an empty ZIP."""
    resp = await client.get(
        "/api/v1/storage/export",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"


@pytest.mark.asyncio
async def test_landing_page(client):
    """Landing page should serve HTML with Windy Cloud title."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "Windy Cloud" in resp.text
    assert "manifest.json" in resp.text
