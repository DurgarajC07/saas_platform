#!/usr/bin/env python3
"""
RAG / Knowledge-Base smoke test (Day 10).

Checks:
  1   Login as platform-admin
  2   Create org + agent (fresh slugs per run)
  3   POST /agents/{id}/knowledge-base — TXT upload → 202, status=pending
  4   GET  /agents/{id}/knowledge-base — list shows 1 document
  5   Returned doc has required fields (id, file_name, file_type, status)
  6   POST second doc (MD file) → 202
  7   GET  /agents/{id}/knowledge-base — list shows 2 documents
  8   DELETE /agents/{id}/knowledge-base/{doc_id} (first doc) → 200
  9   Returned delete response has doc_id + chunks_deleted fields
 10   GET  /agents/{id}/knowledge-base — list shows 1 document after single-delete
 11   DELETE /agents/{id}/knowledge-base (clear all) → 204
 12   GET  /agents/{id}/knowledge-base — list is empty after clear-all
 13   POST with unsupported MIME type → 422 (or rejected gracefully)
 14   GET  /agents/{id}/knowledge-base?status=pending — filter by status works
 15   Tenant isolation: second org+agent → its KB list is empty
 16   No cross-tenant leak: first agent KB unchanged after second org create
 17   Unauthenticated upload → 401

Run (server must be on port 8000):
    python scripts/smoke_test_rag.py
"""

from __future__ import annotations

import io
import sys
import time
import uuid

import requests

BASE = "http://127.0.0.1:8000/api/v1"
EMAIL = "admin@test.com"
PASSWORD = "TestPass123!"

PASS_SYM = "\033[92m✓\033[0m"
FAIL_SYM = "\033[91m✗\033[0m"

ok = errors = 0
_RUN_ID = uuid.uuid4().hex[:6]  # unique suffix so re-runs don't collide


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def check(label: str, cond: bool, detail: str = "") -> None:
    global ok, errors
    sym = PASS_SYM if cond else FAIL_SYM
    suffix = f"  ({detail})" if detail else ""
    print(f"  {sym}  {label}{suffix}")
    if cond:
        ok += 1
    else:
        errors += 1
        print(f"       ↳ FAILED — detail: {detail if detail else 'no detail'}")


def login() -> str:
    r = requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["accessToken"]


def hdr(token: str, org_id: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    if org_id:
        h["X-Organization-ID"] = org_id
    return h


def get_or_create_org(token: str, slug: str, name: str) -> str:
    """Return org_id, creating the org if needed."""
    r = requests.post(
        f"{BASE}/organizations",
        headers=hdr(token),
        json={"name": name, "slug": slug, "plan": "trial"},
    )
    if r.status_code in (200, 201):
        return r.json()["id"]
    if r.status_code == 409:  # already exists
        r2 = requests.get(f"{BASE}/organizations/{slug}", headers=hdr(token))
        assert r2.status_code == 200, f"Cannot fetch existing org: {r2.text}"
        return r2.json()["id"]
    raise AssertionError(f"Cannot create org: {r.status_code} {r.text}")


def create_agent(token: str, org_id: str, name: str, slug_suffix: str = "") -> str:
    """Create a minimal agent and return its id."""
    slug = f"rag-agent-{_RUN_ID}{slug_suffix}"
    r = requests.post(
        f"{BASE}/agents",
        headers=hdr(token, org_id),
        json={
            "name": name,
            "slug": slug,
            "agent_type": "rag_bot",
            "system_prompt": "You are a helpful assistant.",
            "llm_model": "gpt-4o-mini",
        },
    )
    assert r.status_code == 201, f"Create agent failed: {r.status_code} {r.text}"
    return r.json()["id"]


def upload_doc(
    token: str,
    org_id: str,
    agent_id: str,
    file_name: str,
    content: bytes,
    mime: str = "text/plain",
) -> requests.Response:
    return requests.post(
        f"{BASE}/agents/{agent_id}/knowledge-base",
        headers=hdr(token, org_id),
        files={"file": (file_name, io.BytesIO(content), mime)},
        timeout=30,
    )


def list_kb(
    token: str,
    org_id: str,
    agent_id: str,
    status: str | None = None,
) -> requests.Response:
    url = f"{BASE}/agents/{agent_id}/knowledge-base"
    if status:
        url += f"?status={status}"
    return requests.get(url, headers=hdr(token, org_id), timeout=15)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"\n━━━━  RAG Knowledge-Base Smoke Test (run={_RUN_ID})  ━━━━\n")

    # ── 1. Login ─────────────────────────────────────────────────────────────
    print("── Auth ──")
    token = login()
    check("POST /auth/login", bool(token), "JWT obtained")

    # ── 2. Org + Agent ───────────────────────────────────────────────────────
    print("\n── Org + Agent ──")
    org_slug = f"rag-org-{_RUN_ID}"
    org_id = get_or_create_org(token, org_slug, f"RAG Smoke Org {_RUN_ID}")
    check(f"Org created/found  (slug={org_slug})", bool(org_id), org_id)

    agent_id = create_agent(token, org_id, f"RAG Agent {_RUN_ID}")
    check(f"Agent created", bool(agent_id), agent_id)

    # ── 3. Upload TXT doc ────────────────────────────────────────────────────
    print("\n── Knowledge Base: Upload ──")
    txt_content = b"Voice AI FAQ\n\nQ: What is latency? A: The delay between input and response.\nQ: What is TTFB? A: Time To First Byte from TTS.\n" * 5
    r = upload_doc(token, org_id, agent_id, f"faq_{_RUN_ID}.txt", txt_content, "text/plain")
    check("POST /agents/{id}/knowledge-base (TXT)", r.status_code == 202, f"status={r.status_code}")
    body = r.json() if r.status_code == 202 else {}
    check("Upload response has doc_id", "docId" in body, str(body.get("docId", "MISSING")))
    check("Upload response status=pending", body.get("status") == "pending", f"status={body.get('status')}")
    check("Upload response has qdrant_collection", "qdrantCollection" in body, str(body.get("qdrantCollection", "MISSING")))
    doc_id_1 = body.get("docId", "")

    # ── 4 & 5. List shows 1 doc ───────────────────────────────────────────────
    print("\n── Knowledge Base: List ──")
    r = list_kb(token, org_id, agent_id)
    check("GET /agents/{id}/knowledge-base", r.status_code == 200, f"status={r.status_code}")
    data = r.json() if r.status_code == 200 else {}
    check("List total=1 after first upload", data.get("total") == 1, f"total={data.get('total')}")
    docs = data.get("documents", [])
    if docs:
        doc = docs[0]
        check("Doc has required field: id", "id" in doc)
        check("Doc has required field: file_name", "fileName" in doc)
        check("Doc has required field: file_type", "fileType" in doc)
        check("Doc has required field: status", "status" in doc)
        check(
            "Doc status is valid value",
            doc.get("status") in ("pending", "processing", "completed", "failed"),
            f"status={doc.get('status')}",
        )
    else:
        check("Doc list is non-empty", False, "no documents returned")

    # ── 6 & 7. Upload second doc (MD) ────────────────────────────────────────
    print("\n── Knowledge Base: Second Upload ──")
    md_content = b"# Agent Docs\n\n## Overview\nThis agent handles voice calls.\n\n## Features\n- RAG retrieval\n- Low latency\n" * 3
    r = upload_doc(token, org_id, agent_id, f"docs_{_RUN_ID}.md", md_content, "text/markdown")
    check("POST /agents/{id}/knowledge-base (MD)", r.status_code == 202, f"status={r.status_code}")
    doc_id_2 = r.json().get("docId", "") if r.status_code == 202 else ""

    r = list_kb(token, org_id, agent_id)
    data = r.json() if r.status_code == 200 else {}
    check("List total=2 after second upload", data.get("total") == 2, f"total={data.get('total')}")

    # ── 8 & 9. Delete single doc ─────────────────────────────────────────────
    print("\n── Knowledge Base: Delete Single Doc ──")
    if doc_id_1:
        r = requests.delete(
            f"{BASE}/agents/{agent_id}/knowledge-base/{doc_id_1}",
            headers=hdr(token, org_id),
            timeout=15,
        )
        check(
            "DELETE /agents/{id}/knowledge-base/{doc_id}",
            r.status_code == 200,
            f"status={r.status_code}",
        )
        del_body = r.json() if r.status_code == 200 else {}
        check("Delete response has doc_id", str(del_body.get("docId")) == doc_id_1, f"got={del_body.get('docId')}")
        check("Delete response has chunks_deleted", "chunksDeleted" in del_body, str(del_body))
    else:
        check("doc_id_1 available for delete", False, "upload step failed")

    # ── 10. List shows 1 after single-delete ─────────────────────────────────
    r = list_kb(token, org_id, agent_id)
    data = r.json() if r.status_code == 200 else {}
    check("List total=1 after single delete", data.get("total") == 1, f"total={data.get('total')}")

    # ── 11 & 12. Clear all ────────────────────────────────────────────────────
    print("\n── Knowledge Base: Clear All ──")
    r = requests.delete(
        f"{BASE}/agents/{agent_id}/knowledge-base",
        headers=hdr(token, org_id),
        timeout=15,
    )
    check("DELETE /agents/{id}/knowledge-base (clear all)", r.status_code == 204, f"status={r.status_code}")

    r = list_kb(token, org_id, agent_id)
    data = r.json() if r.status_code == 200 else {}
    check("List total=0 after clear-all", data.get("total") == 0, f"total={data.get('total')}")
    check("Documents list is empty", data.get("documents") == [], f"docs={data.get('documents')}")

    # ── 13. Invalid MIME type ─────────────────────────────────────────────────
    print("\n── Knowledge Base: Validation ──")
    r = upload_doc(token, org_id, agent_id, "bad.exe", b"MZexe", "application/x-msdownload")
    check(
        "POST unsupported file type → 422",
        r.status_code == 422,
        f"status={r.status_code}",
    )

    # ── 14. Status filter ─────────────────────────────────────────────────────
    print("\n── Knowledge Base: Status Filter ──")
    # Upload a fresh doc then filter by pending
    upload_doc(token, org_id, agent_id, f"filter_{_RUN_ID}.txt", b"filter test content " * 20, "text/plain")
    r = list_kb(token, org_id, agent_id, status="pending")
    check(
        "GET /knowledge-base?status=pending returns 200",
        r.status_code == 200,
        f"status={r.status_code}",
    )
    filtered = r.json() if r.status_code == 200 else {}
    # Just verify the response shape is valid (doc may move to another state quickly)
    check(
        "Filtered list has documents/total keys",
        "documents" in filtered and "total" in filtered,
        str(filtered),
    )

    # ── 15 & 16. Tenant isolation ─────────────────────────────────────────────
    print("\n── Tenant Isolation ──")
    org2_slug = f"rag-org2-{_RUN_ID}"
    org2_id = get_or_create_org(token, org2_slug, f"RAG Smoke Org2 {_RUN_ID}")
    agent2_id = create_agent(token, org2_id, f"RAG Agent2 {_RUN_ID}", slug_suffix="-b")
    check("Second org+agent created", bool(agent2_id), agent2_id)

    r = list_kb(token, org2_id, agent2_id)
    data2 = r.json() if r.status_code == 200 else {}
    check("Second agent KB is empty (tenant isolation)", data2.get("total") == 0, f"total={data2.get('total')}")

    # Ensure first agent still has the filter-test doc (not crossed tenants)
    r = list_kb(token, org_id, agent_id)
    data1 = r.json() if r.status_code == 200 else {}
    check(
        "First agent KB unaffected by second tenant",
        data1.get("total", 0) >= 1,
        f"total={data1.get('total')}",
    )

    # ── 17. Unauthenticated upload ────────────────────────────────────────────
    print("\n── Auth Guard ──")
    r = requests.post(
        f"{BASE}/agents/{agent_id}/knowledge-base",
        files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        timeout=10,
    )
    check("POST without auth → 401/403", r.status_code in (401, 403), f"status={r.status_code}")

    # ── Summary ───────────────────────────────────────────────────────────────
    total = ok + errors
    print(f"\n━━━━  {ok}/{total} checks passed  ━━━━\n")
    sys.exit(0 if errors == 0 else 1)


if __name__ == "__main__":
    main()
