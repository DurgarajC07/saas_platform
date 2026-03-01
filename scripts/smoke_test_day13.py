#!/usr/bin/env python3
"""
Day 13 smoke test — System Settings, Health, Metrics, Admin Stats.

Checks:
  1  GET  /api/v1/system/health        — public (no auth)
  2  GET  /api/v1/system/settings      — 401 without auth
  3  Login as platform admin
  4  GET  /api/v1/system/settings      — admin sees all (empty initially)
  5  PUT  /api/v1/system/settings/maintenance_mode  — create setting
  6  GET  /api/v1/system/settings/maintenance_mode  — fetch via API
  7  PUT  /api/v1/system/settings/maintenance_mode  — update value (cache invalidation)
  8  GET  /api/v1/system/settings      — list shows the setting
  9  DELETE /api/v1/system/settings/maintenance_mode — delete
 10  GET  /api/v1/system/settings/maintenance_mode  — 404 after delete
 11  GET  /api/v1/admin/stats           — admin dashboard stats
 12  GET  /api/v1/system/metrics        — Prometheus text format
 13  Access control: non-admin → 403 on admin endpoints
"""

import sys
import requests

BASE = "http://127.0.0.1:8000"
PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

ok = errors = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok, errors
    sym = PASS if cond else FAIL
    print(f"  {sym}  {label}" + (f"  ({detail})" if detail else ""))
    if cond:
        ok += 1
    else:
        errors += 1


def login(email: str, password: str) -> str | None:
    r = requests.post(
        f"{BASE}/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    if r.status_code == 200:
        return r.json().get("accessToken")
    return None


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


print("\n=== Day 13 Smoke Test ===\n")

# ── 1. Public health check (no auth) ─────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/system/health")
check("1. GET /system/health — 200 (public)", r.status_code == 200)
if r.status_code == 200:
    body = r.json()
    check("   status field present", "status" in body, body.get("status"))
    check("   components present", "components" in body)
    check("   db component ok", body.get("components", {}).get("database", {}).get("status") == "ok")
    check("   redis component ok", body.get("components", {}).get("redis", {}).get("status") == "ok")

# ── 2. 401 without auth on protected endpoint ────────────────────────────────
r = requests.get(f"{BASE}/api/v1/system/settings")
check("2. GET /system/settings — 401 without auth", r.status_code == 401)

# ── 3. Admin login ────────────────────────────────────────────────────────────
admin_token = login("admin@test.com", "TestPass123!")
check("3. Admin login succeeds", admin_token is not None)
if not admin_token:
    print("\nFATAL: cannot proceed without admin token")
    sys.exit(1)

# ── 4. List settings (empty) ──────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/system/settings", headers=auth(admin_token))
check("4. GET /system/settings (admin) — 200", r.status_code == 200, str(r.text[:100]))
if r.status_code == 200:
    body = r.json()
    check("   settings list field present", "settings" in body)
    check("   count field present", "count" in body)

# ── 5. Create a setting ───────────────────────────────────────────────────────
r = requests.put(
    f"{BASE}/api/v1/system/settings/maintenance_mode",
    headers=auth(admin_token),
    json={"value": False, "description": "Toggle maintenance mode", "isPublic": True},
)
check("5. PUT /system/settings/maintenance_mode — 200", r.status_code == 200, str(r.text[:120]))
if r.status_code == 200:
    body = r.json()
    check("   key matches", body.get("key") == "maintenance_mode")
    check("   value is False", body.get("value") is False)

# ── 6. Fetch single setting ───────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/system/settings/maintenance_mode", headers=auth(admin_token))
check("6. GET /system/settings/maintenance_mode — 200", r.status_code == 200)

# ── 7. Update (cache invalidation) ────────────────────────────────────────────
r = requests.put(
    f"{BASE}/api/v1/system/settings/maintenance_mode",
    headers=auth(admin_token),
    json={"value": True, "isPublic": True},
)
check("7. PUT maintenance_mode → True — 200", r.status_code == 200)
if r.status_code == 200:
    check("   new value is True", r.json().get("value") is True)

# ── 8. List includes the new setting ──────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/system/settings", headers=auth(admin_token))
check("8. GET /system/settings lists updated setting", r.status_code == 200)
if r.status_code == 200:
    keys = [s["key"] for s in r.json().get("settings", [])]
    check("   maintenance_mode in list", "maintenance_mode" in keys)

# ── 9. Delete setting ─────────────────────────────────────────────────────────
r = requests.delete(
    f"{BASE}/api/v1/system/settings/maintenance_mode",
    headers=auth(admin_token),
)
check("9. DELETE /system/settings/maintenance_mode — 204", r.status_code == 204)

# ── 10. 404 after delete ──────────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/system/settings/maintenance_mode", headers=auth(admin_token))
check("10. GET deleted setting — 404", r.status_code == 404)

# ── 11. Admin stats ───────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/admin/stats", headers=auth(admin_token))
check("11. GET /admin/stats — 200", r.status_code == 200, str(r.text[:80]))
if r.status_code == 200:
    body = r.json()
    for field in ["totalUsers", "activeUsers", "totalOrganizations", "mrrUsd", "arrUsd"]:
        check(f"    field {field} present", field in body)

# ── 12. Prometheus metrics ─────────────────────────────────────────────────────
r = requests.get(f"{BASE}/api/v1/system/metrics", headers=auth(admin_token))
check("12. GET /system/metrics — 200 (Prometheus)", r.status_code == 200)
if r.status_code == 200:
    check("   content-type is text/plain", "text/plain" in r.headers.get("content-type", ""))
    check("   contains http_requests_total", "http_requests_total" in r.text)
    check("   contains http_request_duration_seconds", "http_request_duration_seconds" in r.text)

# ── 13. Access control ────────────────────────────────────────────────────────
# Register a normal (non-admin) user and check they get 403 on admin endpoints
import random, string
rand_suffix = "".join(random.choices(string.ascii_lowercase, k=6))
reg = requests.post(
    f"{BASE}/api/v1/auth/register",
    json={
        "email": f"smoke_d13_{rand_suffix}@example.com",
        "password": "TestPass123!",
        "firstName": "Smoke",
        "lastName": "Test",
    },
)
user_token = None
if reg.status_code in (200, 201):
    user_token = login(f"smoke_d13_{rand_suffix}@example.com", "TestPass123!")

if user_token:
    r403 = requests.put(
        f"{BASE}/api/v1/system/settings/some_key",
        headers=auth(user_token),
        json={"value": "evil"},
    )
    check("13. Non-admin PUT /system/settings → 403", r403.status_code == 403)

    r403b = requests.get(f"{BASE}/api/v1/admin/stats", headers=auth(user_token))
    check("    Non-admin GET /admin/stats → 403", r403b.status_code == 403)

    r403c = requests.get(f"{BASE}/api/v1/system/metrics", headers=auth(user_token))
    check("    Non-admin GET /system/metrics → 403", r403c.status_code == 403)
else:
    print("  ⚠  Skipped access-control check (registration failed)")

# ── Summary ───────────────────────────────────────────────────────────────────
total = ok + errors
print(f"\n{'='*45}")
print(f"  Results: {ok}/{total} passed  ({errors} failed)")
print("="*45, "\n")
sys.exit(0 if errors == 0 else 1)
