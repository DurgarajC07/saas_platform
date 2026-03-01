"""
Day 10 Smoke Test — API Key Management & Webhook Delivery
=========================================================
Tests:
 1.  Login and get JWT token
 2.  Create org (for X-Org-Id context)
 3.  Create API key → raw key visible once
 4.  List API keys → raw key hidden, prefix present
 5.  Verify auth via X-API-Key header → 200
 6.  Verify auth via Authorization: Bearer sk_... → 200
 7.  Bad API key → 401
 8.  Create scoped key (api:read) + verify scoped → 200
 9.  Scoped key missing scope (api:write) → 403
10.  Revoke key → isActive: false
11.  Revoked key rejected → 401
12.  Create webhook → 201, signingSecret present
13.  List webhooks → signingSecret NOT in list
14.  Get webhook → 200
15.  Update webhook (deactivate) → isActive: false
16.  List deliveries → 200, empty
17.  Delete webhook → 204
18.  Get deleted webhook → 404
19.  Unauthenticated list-keys → 401

Run:
    redis-cli KEYS "rate:apikey:*" | xargs -r redis-cli DEL
    python scripts/smoke_test_day10.py
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
            body = resp.text[:300]
        print(f"       Response: {json.dumps(body, indent=2)[:400]}")
        sys.exit(1)
    try:
        return resp.json()
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    async with httpx.AsyncClient(timeout=30) as client:

        print("\n━━━━  Day 10 Smoke Test: API Key Management & Webhooks  ━━━━\n")

        # ── 1. Login ──────────────────────────────────────────────────────────
        print("── Auth ──")
        r = await client.post(f"{BASE}/auth/login", json=CREDS)
        data = check("POST /auth/login", r, 200)
        token = data["accessToken"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # ── 2. Get / create org ───────────────────────────────────────────────
        print("\n── Org context ──")
        ORG_SLUG = "smoke-day10-org"
        r = await client.post(
            f"{BASE}/organizations",
            headers=auth_headers,
            json={"name": "Smoke Day10 Org", "slug": ORG_SLUG},
        )
        if r.status_code not in (200, 201, 409):
            check("POST /organizations", r, 201)  # force fail w/ message
        if r.status_code in (200, 201):
            print(f"  ✅  [201] POST /organizations (created)")
        else:
            print(f"  ℹ️   Org already exists, fetching…")

        r = await client.get(f"{BASE}/organizations/{ORG_SLUG}", headers=auth_headers)
        data = check(f"GET /organizations/{ORG_SLUG}", r, 200)
        org_id = data["id"]
        print(f"  ℹ️   org_id={org_id}")

        org_headers = {**auth_headers, "X-Organization-ID": org_id}

        # ── 3. Create API key ─────────────────────────────────────────────────
        print("\n── API Key Management ──")
        r = await client.post(
            f"{BASE}/api-keys",
            headers=org_headers,
            json={"name": "test-key", "scopes": ["api:read", "data:read"], "rateLimitPerMinute": 60},
        )
        data = check("POST /api-keys (create)", r, 201)
        raw_key: str = data["key"]
        key_id: str = data["id"]
        assert raw_key.startswith("sk_live_"), f"Key should start with sk_live_, got: {raw_key[:15]}"
        assert data["prefix"] == raw_key[:10], "prefix mismatch"
        assert "key" in data, "CreateKeyResponse must include raw key"
        print(f"  ℹ️   key_id={key_id}, prefix={data['prefix']}")

        # ── 4. List API keys — no raw key ─────────────────────────────────────
        r = await client.get(f"{BASE}/api-keys", headers=org_headers)
        data = check("GET /api-keys (list)", r, 200)
        keys_list = data.get("keys", [])
        assert len(keys_list) >= 1, "Expected at least one key in list"
        first = keys_list[0]
        assert "key" not in first, "Raw key must NOT appear in list response"
        assert "keyPrefix" in first, "keyPrefix must be present in list"

        # ── 5. Verify via X-API-Key header ───────────────────────────────────
        r = await client.get(
            f"{BASE}/api-keys/verify",
            headers={"X-API-Key": raw_key},
        )
        vdata = check("GET /api-keys/verify (X-API-Key header)", r, 200)
        assert vdata["id"] == key_id

        # ── 6. Verify via Authorization: Bearer sk_... ────────────────────────
        r = await client.get(
            f"{BASE}/api-keys/verify",
            headers={"Authorization": f"Bearer {raw_key}"},
        )
        check("GET /api-keys/verify (Bearer sk_... header)", r, 200)

        # ── 7. Bad key → 401 ──────────────────────────────────────────────────
        r = await client.get(
            f"{BASE}/api-keys/verify",
            headers={"X-API-Key": "sk_live_badkey_notreal_000000000000000000000000"},
        )
        check("GET /api-keys/verify (bad key) → 401", r, 401)

        # ── 8. Scoped key —  api:read scope ──────────────────────────────────
        print("\n── Scope Enforcement ──")
        r = await client.post(
            f"{BASE}/api-keys",
            headers=org_headers,
            json={"name": "scoped-key", "scopes": ["api:read"]},
        )
        data = check("POST /api-keys (create scoped api:read)", r, 201)
        scoped_key: str = data["key"]
        scoped_key_id: str = data["id"]

        r = await client.get(
            f"{BASE}/api-keys/verify-scoped",
            headers={"X-API-Key": scoped_key},
        )
        check("GET /api-keys/verify-scoped (has api:read) → 200", r, 200)

        # ── 9. Key without required scope → 403 ──────────────────────────────
        r = await client.post(
            f"{BASE}/api-keys",
            headers=org_headers,
            json={"name": "write-only-key", "scopes": ["data:write"]},
        )
        data = check("POST /api-keys (create data:write key)", r, 201)
        write_only_key: str = data["key"]

        r = await client.get(
            f"{BASE}/api-keys/verify-scoped",
            headers={"X-API-Key": write_only_key},
        )
        check("GET /api-keys/verify-scoped (lacks api:read) → 403", r, 403)

        # ── 10. Revoke key ────────────────────────────────────────────────────
        print("\n── Revocation ──")
        r = await client.delete(
            f"{BASE}/api-keys/{key_id}",
            headers=org_headers,
        )
        data = check("DELETE /api-keys/{id} (revoke)", r, 200)
        assert data["isActive"] is False, "Revoked key must have isActive=false"

        # ── 11. Revoked key rejected → 401 ────────────────────────────────────
        r = await client.get(
            f"{BASE}/api-keys/verify",
            headers={"X-API-Key": raw_key},
        )
        check("GET /api-keys/verify (revoked key) → 401", r, 401)

        # ── 12. Create webhook ────────────────────────────────────────────────
        print("\n── Webhook Management ──")
        r = await client.post(
            f"{BASE}/webhooks",
            headers=org_headers,
            json={
                "url": "https://httpbin.org/post",
                "events": ["user.created", "billing.subscription.created"],
                "name": "test-webhook",
            },
        )
        data = check("POST /webhooks (create)", r, 201)
        webhook_id: str = data["id"]
        signing_secret: str = data.get("signingSecret", "")
        assert signing_secret, "signingSecret must be present in create response"
        assert len(signing_secret) >= 40, f"Expected ~43 char secret, got: {len(signing_secret)}"
        print(f"  ℹ️   webhook_id={webhook_id}, secret_len={len(signing_secret)}")

        # ── 13. List webhooks — no signingSecret ─────────────────────────────
        r = await client.get(f"{BASE}/webhooks", headers=org_headers)
        data = check("GET /webhooks (list)", r, 200)
        wh_list = data.get("webhooks", [])
        assert len(wh_list) >= 1, "Expected at least one webhook"
        assert "signingSecret" not in wh_list[0], "signingSecret must NOT appear in list"

        # ── 14. Get webhook ───────────────────────────────────────────────────
        r = await client.get(f"{BASE}/webhooks/{webhook_id}", headers=org_headers)
        data = check(f"GET /webhooks/{webhook_id}", r, 200)
        assert data["id"] == webhook_id

        # ── 15. Update webhook (deactivate) ───────────────────────────────────
        r = await client.patch(
            f"{BASE}/webhooks/{webhook_id}",
            headers=org_headers,
            json={"isActive": False},
        )
        data = check("PATCH /webhooks/{id} (deactivate)", r, 200)
        assert data["isActive"] is False

        # ── 16. List deliveries ───────────────────────────────────────────────
        r = await client.get(
            f"{BASE}/webhooks/{webhook_id}/deliveries",
            headers=org_headers,
        )
        data = check("GET /webhooks/{id}/deliveries", r, 200)
        assert "deliveries" in data

        # ── 17. Delete webhook ────────────────────────────────────────────────
        r = await client.delete(
            f"{BASE}/webhooks/{webhook_id}",
            headers=org_headers,
        )
        check("DELETE /webhooks/{id}", r, 204)

        # ── 18. Get deleted webhook → 404 ─────────────────────────────────────
        r = await client.get(f"{BASE}/webhooks/{webhook_id}", headers=org_headers)
        check("GET /webhooks/{id} (deleted) → 404", r, 404)

        # ── 19. Unauthenticated → 401 ────────────────────────────────────────
        print("\n── Access control ──")
        r = await client.get(f"{BASE}/api-keys")
        check("GET /api-keys (no auth) → 401", r, 401)

        # ── Clean up extra keys ───────────────────────────────────────────────
        for kid in (scoped_key_id,):
            await client.delete(f"{BASE}/api-keys/{kid}", headers=org_headers)
        data_wr = (await client.get(f"{BASE}/api-keys", headers=org_headers)).json()
        for k in data_wr.get("keys", []):
            if k["name"] == "write-only-key":
                await client.delete(f"{BASE}/api-keys/{k['id']}", headers=org_headers)

        print("\n━━━━  All Day 10 checks passed  ━━━━\n")


if __name__ == "__main__":
    asyncio.run(main())
