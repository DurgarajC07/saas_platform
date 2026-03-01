"""
Day 11 Smoke Test — Notification Module
========================================
Tests:
 1.  Login
 2.  GET /notifications            → 200, empty initially (for this user)
 3.  GET /notifications/count      → 200, unread_count ≥ 0
 4.  POST /notifications/test-send → 201, in_app channel
 5.  GET /notifications            → 200, ≥ 1 notification
 6.  GET /notifications?isRead=false → 200, contains unread
 7.  GET /notifications/count      → 200, unread_count ≥ 1
 8.  PUT /notifications/{id}/read  → 200, is_read: true
 9.  GET /notifications/count (after mark-read) → unread decremented
10.  POST another notification, then PUT /notifications/read-all → marked_count ≥ 1
11.  GET /notifications?isRead=false → 200, empty (all read)
12.  GET /notifications/preferences → 200, list (may be empty initially)
13.  PUT /notifications/preferences → 200, upsert email + sms + push prefs
14.  GET /notifications/preferences → 200, updated prefs present
15.  Disable email channel pref, GET preferences → is_enabled: false
16.  GET /notifications?type=system.test → 200, filtered correctly
17.  No-auth → 401 on all protected endpoints

Run:
    /path/to/.venv/bin/python scripts/smoke_test_day11.py
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
            body = resp.text[:400]
        print(f"       Response: {json.dumps(body, indent=2)[:500]}")
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

        print("\n━━━━  Day 11 Smoke Test: Notification Module  ━━━━\n")

        # ── 1. Login ──────────────────────────────────────────────────────────
        print("── Auth ──")
        r = await client.post(f"{BASE}/auth/login", json=CREDS)
        data = check("POST /auth/login", r, 200)
        token = data["accessToken"]
        hdrs = {"Authorization": f"Bearer {token}"}

        # ── 2. List notifications (initially may be empty or not — just 200) ──
        print("\n── Listing ──")
        r = await client.get(f"{BASE}/notifications", headers=hdrs)
        data = check("GET /notifications (initial)", r, 200)
        assert "notifications" in data, "Missing 'notifications' key"
        assert "pagination" in data, "Missing 'pagination' key"
        initial_total = data["pagination"]["totalItems"]
        print(f"  ℹ️   existing notifications: {initial_total}")

        # ── 3. Unread count ───────────────────────────────────────────────────
        r = await client.get(f"{BASE}/notifications/count", headers=hdrs)
        data = check("GET /notifications/count (initial)", r, 200)
        initial_unread = data["unreadCount"]
        assert isinstance(initial_unread, int) and initial_unread >= 0
        print(f"  ℹ️   initial unread: {initial_unread}")

        # ── 4. Send test notification ─────────────────────────────────────────
        print("\n── Send test notification ──")
        r = await client.post(
            f"{BASE}/notifications/test-send",
            headers=hdrs,
            json={
                "type": "system.test",
                "title": "Smoke Test Notification",
                "body": "Hello from smoke test",
                "data": {"smoke": True},
            },
        )
        data = check("POST /notifications/test-send", r, 201)
        notif_id: str = data["id"]
        assert data["channel"] == "in_app", "Expected in_app channel"
        assert data["isRead"] is False, "New notification must be unread"
        assert data["type"] == "system.test"
        assert data["title"] == "Smoke Test Notification"
        print(f"  ℹ️   notif_id={notif_id}")

        # ── 5. List — should now contain at least the new one ─────────────────
        r = await client.get(f"{BASE}/notifications", headers=hdrs)
        data = check("GET /notifications (after send)", r, 200)
        new_total = data["pagination"]["totalItems"]
        assert new_total == initial_total + 1, f"Expected {initial_total+1} total, got {new_total}"

        # ── 6. Filter by is_read=false ────────────────────────────────────────
        r = await client.get(f"{BASE}/notifications?is_read=false", headers=hdrs)
        data = check("GET /notifications?is_read=false", r, 200)
        unread_items = data["notifications"]
        assert any(n["id"] == notif_id for n in unread_items), "New notif must appear in unread list"

        # ── 7. Unread count increased ─────────────────────────────────────────
        r = await client.get(f"{BASE}/notifications/count", headers=hdrs)
        data = check("GET /notifications/count (after send)", r, 200)
        assert data["unreadCount"] == initial_unread + 1, (
            f"Expected {initial_unread + 1} unread, got {data['unreadCount']}"
        )

        # ── 8. Mark single read ───────────────────────────────────────────────
        print("\n── Mark read ──")
        r = await client.put(f"{BASE}/notifications/{notif_id}/read", headers=hdrs)
        data = check(f"PUT /notifications/{{{notif_id[:8]}…}}/read", r, 200)
        assert data["notification"]["isRead"] is True, "isRead must be true after marking"
        assert data["notification"]["readAt"] is not None, "readAt must be set"

        # ── 9. Unread count decremented ───────────────────────────────────────
        r = await client.get(f"{BASE}/notifications/count", headers=hdrs)
        data = check("GET /notifications/count (after mark-read)", r, 200)
        assert data["unreadCount"] == initial_unread, (
            f"Expected {initial_unread} unread, got {data['unreadCount']}"
        )

        # ── 10. Send another, then mark-all-read ─────────────────────────────
        print("\n── Mark all read ──")
        await client.post(
            f"{BASE}/notifications/test-send",
            headers=hdrs,
            json={"type": "system.test", "title": "Another", "body": "Test 2"},
        )
        await client.post(
            f"{BASE}/notifications/test-send",
            headers=hdrs,
            json={"type": "billing.alert", "title": "Bill", "body": "Due today"},
        )

        r = await client.put(f"{BASE}/notifications/read-all", headers=hdrs)
        data = check("PUT /notifications/read-all", r, 200)
        assert data["markedCount"] >= 1, f"Expected ≥ 1 marked, got {data['markedCount']}"
        print(f"  ℹ️   marked {data['markedCount']} as read")

        # ── 11. All read — unread filter returns empty ────────────────────────
        r = await client.get(f"{BASE}/notifications?is_read=false&channel=in_app", headers=hdrs)
        data = check("GET /notifications?is_read=false&channel=in_app (all read)", r, 200)
        assert len(data["notifications"]) == 0, (
            f"Expected 0 unread in_app after mark-all-read, got {len(data['notifications'])}"
        )

        # ── 12. Get preferences (initially empty / no custom rows) ────────────
        print("\n── Preferences ──")
        r = await client.get(f"{BASE}/notifications/preferences", headers=hdrs)
        data = check("GET /notifications/preferences (initial)", r, 200)
        assert "preferences" in data
        initial_pref_count = len(data["preferences"])
        print(f"  ℹ️   existing preferences: {initial_pref_count}")

        # ── 13. Update preferences ────────────────────────────────────────────
        r = await client.put(
            f"{BASE}/notifications/preferences",
            headers=hdrs,
            json={
                "preferences": [
                    {"notificationType": "billing.alert", "channel": "email", "isEnabled": True},
                    {"notificationType": "billing.alert", "channel": "sms", "isEnabled": False},
                    {"notificationType": "system.test", "channel": "push", "isEnabled": True},
                ]
            },
        )
        data = check("PUT /notifications/preferences (upsert 3)", r, 200)
        upserted = data["preferences"]
        assert len(upserted) == 3, f"Expected 3 upserted prefs, got {len(upserted)}"

        # ── 14. Verify stored preferences ────────────────────────────────────
        r = await client.get(f"{BASE}/notifications/preferences", headers=hdrs)
        data = check("GET /notifications/preferences (after update)", r, 200)
        pref_map = {
            f"{p['notificationType']}:{p['channel']}": p["isEnabled"]
            for p in data["preferences"]
        }
        assert pref_map.get("billing.alert:email") is True, "billing.alert:email should be enabled"
        assert pref_map.get("billing.alert:sms") is False, "billing.alert:sms should be disabled"
        assert pref_map.get("system.test:push") is True, "system.test:push should be enabled"
        print(f"  ℹ️   {len(data['preferences'])} preferences stored")

        # ── 15. Disable email pref ────────────────────────────────────────────
        r = await client.put(
            f"{BASE}/notifications/preferences",
            headers=hdrs,
            json={
                "preferences": [
                    {"notificationType": "billing.alert", "channel": "email", "isEnabled": False},
                ]
            },
        )
        data = check("PUT /notifications/preferences (disable email)", r, 200)
        updated_pref = data["preferences"][0]
        assert updated_pref["isEnabled"] is False, "email pref should now be disabled"

        # ── 16. Filter by notification type ───────────────────────────────────
        print("\n── Filtering ──")
        r = await client.get(
            f"{BASE}/notifications?notification_type=billing.alert",
            headers=hdrs,
        )
        data = check("GET /notifications?notification_type=billing.alert", r, 200)
        assert all(
            n["type"] == "billing.alert" for n in data["notifications"]
        ), "All returned notifications should be type billing.alert"

        # Filter by channel
        r = await client.get(
            f"{BASE}/notifications?channel=in_app",
            headers=hdrs,
        )
        data = check("GET /notifications?channel=in_app", r, 200)
        assert all(
            n["channel"] == "in_app" for n in data["notifications"]
        ), "All returned notifications should be channel in_app"

        # ── 17. Unauthenticated → 401 ─────────────────────────────────────────
        print("\n── Access control ──")
        for path, method in [
            ("/notifications", "GET"),
            ("/notifications/count", "GET"),
            ("/notifications/preferences", "GET"),
        ]:
            r = await client.request(method, f"{BASE}{path}")
            check(f"{method} {path} (no auth) → 401", r, 401)

        print("\n━━━━  All Day 11 checks passed  ━━━━\n")


if __name__ == "__main__":
    asyncio.run(main())
