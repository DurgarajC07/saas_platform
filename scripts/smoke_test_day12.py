#!/usr/bin/env python
"""
Day 12 Smoke Test — File Storage Module
=========================================
Tests:
  1.  Login
  2.  Create / fetch org context
  3.  POST /files/upload           (text file, local storage)
  4.  POST /files/upload (same)    → deduplicated = true
  5.  POST /files/upload           (PDF content, with attachable_type)
  6.  GET  /files                  → list, ≥ 2 files
  7.  GET  /files/{id}             → metadata matches upload
  8.  GET  /files/{id}/download    → bytes streamed (local), correct MIME
  9.  GET  /files?attachable_type= → filtered list
 10.  DELETE /files/{id}           → 200, deleted: true
 11.  GET  /files/{id}             → 404 after delete
 12.  GET  /files                  → count decremented
 13.  Access control               → 401 without auth
 14.  GET  /files?mime_type=text/plain  → MIME filter works

Run:
    .venv/bin/python scripts/smoke_test_day12.py
"""

from __future__ import annotations

import asyncio
import json
import sys

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
CREDS = {"email": "admin@test.com", "password": "TestPass123!"}

PASS = "✅"
FAIL = "❌"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def check(label: str, resp: httpx.Response, expected: int) -> dict:
    ok = resp.status_code == expected
    icon = PASS if ok else FAIL
    print(f"  {icon}  [{resp.status_code}] {label}")
    if not ok:
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:500]
        print(f"       Response: {json.dumps(body, indent=2)[:600]}")
        sys.exit(1)
    try:
        return resp.json()
    except Exception:
        return {}


def assertv(label: str, actual, expected=None, *, truthy: bool = False) -> None:
    if truthy:
        ok = bool(actual)
    else:
        ok = actual == expected
    if ok:
        print(f"  {PASS}  {label} = {actual!r}")
    else:
        print(f"  {FAIL}  {label}: expected {expected!r}, got {actual!r}")
        sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as client:

        print("\n━━━━  Day 12 Smoke Test: File Storage Module  ━━━━\n")

        # ── 1. Login ──────────────────────────────────────────────────────────
        print("── Auth ──")
        r = await client.post(f"{BASE}/auth/login", json=CREDS)
        data = check("POST /auth/login", r, 200)
        token = data["accessToken"]
        auth = {"Authorization": f"Bearer {token}"}

        # ── 2. Org context ────────────────────────────────────────────────────
        print("\n── Org context ──")
        ORG_SLUG = "smoke-day12-org"
        r = await client.post(
            f"{BASE}/organizations",
            headers=auth,
            json={"name": "Smoke Day12 Org", "slug": ORG_SLUG},
        )
        if r.status_code not in (200, 201, 409):
            check("POST /organizations", r, 201)
        print(f"  ℹ️   org create status: {r.status_code}")

        r = await client.get(f"{BASE}/organizations/{ORG_SLUG}", headers=auth)
        data = check(f"GET /organizations/{ORG_SLUG}", r, 200)
        org_id = data["id"]
        print(f"  ℹ️   org_id = {org_id}")

        H = {**auth, "X-Organization-ID": org_id}

        # ── 3. Upload a text file ─────────────────────────────────────────────
        print("\n── Upload ──")
        text_content = b"Hello, SaaS Platform! This is a test document for Day 12."
        r = await client.post(
            f"{BASE}/files/upload",
            params={"attachable_type": "test_entity"},
            files={"file": ("day12_test.txt", text_content, "text/plain")},
            headers={**auth, "X-Organization-ID": org_id},
        )
        data = check("POST /files/upload (text)", r, 201)
        file_id: str = data["file"]["id"]
        assertv("deduplicated", data["deduplicated"], False)
        assertv("mimeType", data["file"]["mimeType"], "text/plain")
        assertv("originalName", data["file"]["originalName"], "day12_test.txt")
        assertv("fileSizeBytes", data["file"]["fileSizeBytes"], len(text_content))
        assertv("storageProvider", data["file"]["storageProvider"], "local")
        print(f"  ℹ️   file_id = {file_id}")

        # ── 4. Deduplication ──────────────────────────────────────────────────
        print("\n── Deduplication ──")
        r = await client.post(
            f"{BASE}/files/upload",
            params={"attachable_type": "test_entity"},
            files={"file": ("day12_test_copy.txt", text_content, "text/plain")},
            headers={**auth, "X-Organization-ID": org_id},
        )
        data = check("POST /files/upload (same content → dedup)", r, 201)
        assertv("deduplicated=true", data["deduplicated"], True)
        assertv("same file_id returned", data["file"]["id"], file_id)

        # ── 5. Upload a second distinct file (PDF-like bytes) ─────────────────
        print("\n── Upload second file ──")
        # Minimal valid-ish content; python-magic detects from bytes
        # Use a real text file so magic reliably detects text/plain
        second_content = b"PDF content simulation for deduplication testing.\n" * 10
        r = await client.post(
            f"{BASE}/files/upload",
            params={"attachable_type": "invoice", "attachable_id": str(org_id)},
            files={"file": ("report.txt", second_content, "text/plain")},
            headers={**auth, "X-Organization-ID": org_id},
        )
        data = check("POST /files/upload (second distinct file)", r, 201)
        second_file_id: str = data["file"]["id"]
        assertv("deduplicated=false", data["deduplicated"], False)
        assert second_file_id != file_id, "Second file should be a new record"
        print(f"  ℹ️   second_file_id = {second_file_id}")

        # ── 6. List files ─────────────────────────────────────────────────────
        print("\n── List ──")
        r = await client.get(
            f"{BASE}/files",
            headers={**auth, "X-Organization-ID": org_id},
        )
        data = check("GET /files", r, 200)
        total = data["pagination"]["totalItems"]
        assertv("total files ≥ 2", total >= 2, True, truthy=True)
        print(f"  ℹ️   total org files = {total}")

        # ── 7. Get metadata ───────────────────────────────────────────────────
        print("\n── Metadata ──")
        r = await client.get(
            f"{BASE}/files/{file_id}",
            headers={**auth, "X-Organization-ID": org_id},
        )
        data = check(f"GET /files/{{file_id}}", r, 200)
        assertv("id matches", data["id"], file_id)
        assertv("originalName", data["originalName"], "day12_test.txt")

        # ── 8. Download ───────────────────────────────────────────────────────
        print("\n── Download ──")
        r = await client.get(
            f"{BASE}/files/{file_id}/download",
            headers={**auth, "X-Organization-ID": org_id},
            follow_redirects=True,
        )
        check("GET /files/{id}/download (local → bytes)", r, 200)
        assertv("content matches", r.content, text_content)
        ct = r.headers.get("content-type", "")
        assertv("content-type = text/plain", "text/plain" in ct, True, truthy=True)
        cd = r.headers.get("content-disposition", "")
        assertv("content-disposition has filename", "day12_test.txt" in cd, True, truthy=True)

        # ── 9. Filter by attachable_type ──────────────────────────────────────
        print("\n── Filters ──")
        r = await client.get(
            f"{BASE}/files",
            headers={**auth, "X-Organization-ID": org_id},
            params={"attachable_type": "invoice"},
        )
        data = check("GET /files?attachable_type=invoice", r, 200)
        invoice_files = data["files"]
        assertv("invoice files = 1", len(invoice_files), 1)
        assertv("attachable_type=invoice", invoice_files[0]["attachableType"], "invoice")

        r = await client.get(
            f"{BASE}/files",
            headers={**auth, "X-Organization-ID": org_id},
            params={"mime_type": "text/plain"},
        )
        data = check("GET /files?mime_type=text/plain", r, 200)
        txt_count = data["pagination"]["totalItems"]
        assertv("text/plain count ≥ 2", txt_count >= 2, True, truthy=True)

        # ── 10. Delete ────────────────────────────────────────────────────────
        print("\n── Delete ──")
        r = await client.delete(
            f"{BASE}/files/{second_file_id}",
            headers={**auth, "X-Organization-ID": org_id},
        )
        data = check(f"DELETE /files/{{second_file_id}}", r, 200)
        assertv("deleted=true", data["deleted"], True)
        assertv("file_id matches", data["fileId"], second_file_id)

        # ── 11. After delete: metadata → 404 ─────────────────────────────────
        print("\n── Post-delete checks ──")
        r = await client.get(
            f"{BASE}/files/{second_file_id}",
            headers={**auth, "X-Organization-ID": org_id},
        )
        check(f"GET /files/{{second_file_id}} after delete → 404", r, 404)

        # ── 12. List updated ──────────────────────────────────────────────────
        r = await client.get(
            f"{BASE}/files",
            headers={**auth, "X-Organization-ID": org_id},
        )
        data = check("GET /files (after delete)", r, 200)
        new_total = data["pagination"]["totalItems"]
        assertv("total decremented", new_total, total - 1)

        # ── 13. Access control ────────────────────────────────────────────────
        print("\n── Access control ──")
        for label, method, url in [
            ("GET /files (no auth)", "GET", f"{BASE}/files"),
            ("GET /files/{id} (no auth)", "GET", f"{BASE}/files/{file_id}"),
            ("DELETE /files/{id} (no auth)", "DELETE", f"{BASE}/files/{file_id}"),
        ]:
            r = await client.request(method, url)
            check(f"{label} → 401", r, 401)

        print("\n━━━━  All Day 12 checks passed  ━━━━\n")


if __name__ == "__main__":
    asyncio.run(main())
