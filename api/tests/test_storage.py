"""Storage CRUD tests."""

from __future__ import annotations

import pytest

from api.app.config import settings


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
    # Wave 7 G18: default_storage_quota now tracks tier_quota_free (5 GB)
    # instead of the legacy 500 MB. One number for "free tier", everywhere.
    assert usage["quota_bytes"] == settings.tier_quota_free

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
    """Plans endpoint should be public (no auth required).

    Wave 7 G17 unified the vocabulary; 2026-08-07 replaced it with the
    ecosystem canon (windy-pro/docs/PRICING-TIERS.md), so the list is
    driven by TIER_ORDER rather than a hardcoded copy of it.
    """
    from api.app.routes.billing import TIER_ORDER

    resp = await client.get("/api/v1/storage/plans")
    assert resp.status_code == 200
    plans = resp.json()["plans"]
    assert [p["plan_id"] for p in plans] == list(TIER_ORDER)
    assert plans[0]["price_cents_per_month"] == 0
    assert plans[0]["storage_display"] == "500 MB"   # free
    assert plans[1]["storage_display"] == "5 GB"     # pro
    assert plans[2]["storage_display"] == "25 GB"    # translate  / Windy Ultra
    assert plans[3]["storage_display"] == "100 GB"   # translate_pro / Windy Max
    assert plans[4]["storage_display"] == "1 TB"     # tempest
    assert plans[5]["storage_display"] == "2 TB"     # tornado


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


@pytest.mark.asyncio
async def test_upload_sanitizes_hostile_product_and_file_type(client):
    """Hostile `product` / `file_type` must not inject path segments into the
    storage key (regression: raw `../../evil` 500'd on R2 and was a traversal
    write on the local-disk provider). The upload should succeed with the
    values confined to a safe single-segment slug."""
    resp = await client.post(
        "/api/v1/storage/upload",
        files={"file": ("ok.txt", b"data", "text/plain")},
        data={"product": "../../evil", "file_type": "../etc"},
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    key = resp.json()["key"]
    # The key is `{identity}/{product}/{file_type}/{filename}` — the product and
    # file_type slots must not contain traversal or extra separators.
    segments = key.split("/")
    assert ".." not in key
    # identity / product / file_type / filename == exactly 4 segments
    assert len(segments) == 4, key

    # And it lists back under the sanitized product name (no slashes).
    resp = await client.get(
        "/api/v1/storage/files",
        headers={"Authorization": "Bearer fake"},
    )
    assert resp.status_code == 200
    products = {f["product"] for f in resp.json()["files"]}
    assert all("/" not in p and ".." not in p for p in products)


# ─── Plan card display (2026-08-07) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_prices_show_cents_and_hurricane_is_custom(client):
    """Two live bugs caught on the deployed site, not in a test:

    · `:.0f` rounded $4.99 to "$5" and $8.99 to "$9". EVERY consumer price on
      the ladder ends in .99, so the page advertised the wrong number on the
      three plans most people buy.
    · Hurricane is priced 0 because it is sold per contract. "Free" was the
      fallback for 0, so a 5 TB enterprise plan advertised itself as free.
    """
    resp = await client.get("/api/v1/storage/plans")
    assert resp.status_code == 200
    by_id = {p["plan_id"]: p for p in resp.json()["plans"]}

    assert by_id["free"]["price_display"] == "Free"
    assert by_id["pro"]["price_display"] == "$4.99/mo"
    assert by_id["translate"]["price_display"] == "$8.99/mo"
    assert by_id["translate_pro"]["price_display"] == "$14.99/mo"
    # Whole-dollar prices keep the tidy form.
    assert by_id["tempest"]["price_display"] == "$49/mo"
    assert by_id["tornado"]["price_display"] == "$99/mo"
    # Sold per contract — never "Free".
    assert by_id["hurricane"]["price_display"] == "Custom"
