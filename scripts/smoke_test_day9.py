#!/usr/bin/env python
"""
Day 9 smoke test — Audit + Security modules.

Sections:
  1. Auth
  2. Audit: list, get, export (platform admin only)
  3. Security: login-attempts, blocked-ips CRUD, security events
  4. IP block middleware verification
"""

from __future__ import annotations

import asyncio
import httpx
import redis.asyncio as aioredis

BASE = "http://localhost:8000/api/v1"
REDIS_URL = "redis://localhost:6379/0"
EMAIL = "admin@test.com"
PASSWORD = "TestPass123!"


def hdr(token: str, org_id: str | None = None) -> dict:
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if org_id:
        h["X-Organization-ID"] = org_id
    return h


def check(label: str, resp: httpx.Response, expected: int) -> None:
    symbol = "✓" if resp.status_code == expected else "✗"
    print(f"  {symbol} [{resp.status_code}] {label}")
    if resp.status_code != expected:
        try:
            print(f"    → {resp.json()}")
        except Exception:
            print(f"    → {resp.text[:300]}")


async def main() -> None:
    # Clear any stale blocked_ip keys from previous runs
    r_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    keys = await r_client.keys("blocked_ip:*")
    if keys:
        await r_client.delete(*keys)
        print(f"[setup] Cleared {len(keys)} stale blocked_ip key(s): {keys}")
    await r_client.aclose()

    async with httpx.AsyncClient(timeout=15) as c:
        # ── Auth ────────────────────────────────────────────────────────
        print("\n=== Auth ===")
        r = await c.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
        check("POST /auth/login", r, 200)
        token = r.json()["accessToken"]

        # ── Audit: list logs ─────────────────────────────────────────────
        print("\n=== Audit: List Logs ===")
        r = await c.get(f"{BASE}/audit/logs", headers=hdr(token))
        check("GET  /audit/logs", r, 200)
        data = r.json()
        total = data.get("pagination", {}).get("totalItems", 0)
        print(f"  → {total} total audit entries")

        # List with filter
        r = await c.get(f"{BASE}/audit/logs?action=login", headers=hdr(token))
        check("GET  /audit/logs?action=login", r, 200)
        login_count = r.json().get("pagination", {}).get("totalItems", 0)
        print(f"  → {login_count} login-action entries")

        # ── Audit: get single by id ────────────────────────────────────
        logs = data.get("logs", [])
        if logs:
            log_id = logs[0]["id"]
            print("\n=== Audit: Get Single Entry ===")
            r = await c.get(f"{BASE}/audit/logs/{log_id}", headers=hdr(token))
            check(f"GET  /audit/logs/{{id}}", r, 200)
            entry = r.json()
            print(f"  → action={entry.get('action')}, diff_fields={len(entry.get('diff', {}))}")
        else:
            print("\n  ~ No audit entries yet — skipping single entry test")

        # ── Audit: export CSV ──────────────────────────────────────────
        print("\n=== Audit: Export CSV ===")
        r = await c.get(f"{BASE}/audit/logs/export", headers=hdr(token))
        check("GET  /audit/logs/export", r, 200)
        if r.status_code == 200:
            lines = r.text.strip().split("\n")
            print(f"  → {len(lines)} lines in CSV (header + {len(lines)-1} rows)")
            print(f"  → Content-Disposition: {r.headers.get('content-disposition', 'N/A')}")

        # ── Security: login attempts ───────────────────────────────────
        print("\n=== Security: Login Attempts ===")
        r = await c.get(f"{BASE}/security/login-attempts", headers=hdr(token))
        check("GET  /security/login-attempts", r, 200)
        att_total = r.json().get("pagination", {}).get("totalItems", 0)
        print(f"  → {att_total} total login attempts")

        # Filter by success=false
        r = await c.get(
            f"{BASE}/security/login-attempts?is_success=false", headers=hdr(token)
        )
        check("GET  /security/login-attempts?isSuccess=false", r, 200)
        fail_count = r.json().get("pagination", {}).get("totalItems", 0)
        print(f"  → {fail_count} failed attempts")

        # ── Security: blocked-ips list ────────────────────────────────
        print("\n=== Security: Blocked IPs ===")
        r = await c.get(f"{BASE}/security/blocked-ips", headers=hdr(token))
        check("GET  /security/blocked-ips", r, 200)
        blocked_count = r.json().get("pagination", {}).get("totalItems", 0)
        print(f"  → {blocked_count} currently blocked IPs")

        # ── Security: block an IP ─────────────────────────────────────
        print("\n=== Security: Block IP ===")
        TEST_IP = "192.0.2.99"
        r = await c.post(
            f"{BASE}/security/blocked-ips",
            headers=hdr(token),
            json={"ipAddress": TEST_IP, "reason": "Smoke test block", "hours": 1},
        )
        if r.status_code == 409:
            print(f"  ~ [409] IP {TEST_IP} already blocked — will try to find and unblock first")
            # Look up the existing blocked record
            r2 = await c.get(f"{BASE}/security/blocked-ips?page_size=100", headers=hdr(token))
            blocked_list = r2.json().get("blockedIps", [])
            existing = next((b for b in blocked_list if b["ipAddress"] == TEST_IP), None)
            if existing:
                bid = existing["id"]
                await c.delete(f"{BASE}/security/blocked-ips/{bid}", headers=hdr(token))
                # Retry
                r = await c.post(
                    f"{BASE}/security/blocked-ips",
                    headers=hdr(token),
                    json={"ipAddress": TEST_IP, "reason": "Smoke test block", "hours": 1},
                )
        check("POST /security/blocked-ips", r, 201)
        blocked_id = None
        if r.status_code == 201:
            blocked_id = r.json().get("id")
            print(f"  → blocked_id={blocked_id}, ip={r.json().get('ipAddress')}")

        # ── Security: verify IP block middleware hits Redis ───────────
        print("\n=== Security: IP Block Middleware ===")
        # uvicorn trusts X-Forwarded-For from 127.0.0.1 by default
        # Sending X-Forwarded-For: 192.0.2.99 makes the server see ip=192.0.2.99
        # That IP IS blocked → should return 403
        r3 = await c.get(
            f"{BASE}/security/blocked-ips",
            headers={**hdr(token), "X-Forwarded-For": TEST_IP},
        )
        check("GET  /security/blocked-ips (blocked IP via X-Forwarded-For → 403)", r3, 403)

        # Confirm our real IP (no forwarded header) is NOT blocked → 200
        r4 = await c.get(
            f"{BASE}/security/blocked-ips",
            headers=hdr(token),
        )
        check("GET  /security/blocked-ips (direct connection, not blocked → 200)", r4, 200)

        # ── Security: unblock it ──────────────────────────────────────
        if blocked_id:
            print("\n=== Security: Unblock IP ===")
            r = await c.delete(
                f"{BASE}/security/blocked-ips/{blocked_id}", headers=hdr(token)
            )
            check(f"DELETE /security/blocked-ips/{{id}}", r, 204)

        # ── Security: events ──────────────────────────────────────────
        print("\n=== Security: Events ===")
        r = await c.get(
            f"{BASE}/security/events?hours=24&min_failures=1", headers=hdr(token)
        )
        check("GET  /security/events", r, 200)
        events = r.json()
        print(f"  → {len(events)} suspicious IPs in last 24h")
        for ev in events[:3]:
            print(
                f"    ip={ev.get('ipAddress')}, "
                f"failures={ev.get('failureCount')}, "
                f"blocked={ev.get('isBlocked')}"
            )

        # ── Non-admin access denied ────────────────────────────────────
        print("\n=== Access Control ===")
        # No token → 401
        r = await c.get(f"{BASE}/audit/logs")
        check("GET  /audit/logs (no auth)", r, 401)

        print("\n=== Day 9 smoke test complete ===\n")


if __name__ == "__main__":
    asyncio.run(main())
