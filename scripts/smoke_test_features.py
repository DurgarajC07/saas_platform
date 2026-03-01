#!/usr/bin/env python
"""
Day 8 smoke test — Features module

Covers all 6 endpoints:
  ✓ GET  /features                               (public list)
  ✓ POST /admin/features                         (create feature)
  ✓ POST /admin/plans/{id}/features              (assign to plan)
  ✓ GET  /features/check?keys=…                  (org-scoped check)
  ✓ POST /admin/organizations/{id}/feature-overrides  (grant override)
  ✓ GET  /features/check?keys=…                  (check after override)
  ✓ DELETE /admin/organizations/{id}/feature-overrides/{fid}
  ✓ GET  /features/check?keys=…                  (check after override removed)
"""

from __future__ import annotations

import asyncio
import httpx

BASE = "http://localhost:8000/api/v1"
EMAIL = "admin@test.com"
PASSWORD = "TestPass123!"
ORG_SLUG = "feature-smoke-org-001"


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
            print(f"    → {resp.text[:200]}")


async def main() -> None:
    async with httpx.AsyncClient(timeout=15) as c:
        # ── Auth ──────────────────────────────────────────────────────────
        print("\n=== Auth ===")
        r = await c.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
        check("POST /auth/login", r, 200)
        token = r.json()["accessToken"]

        # ── Setup org ─────────────────────────────────────────────────────
        print("\n=== Setup Org ===")
        r = await c.get(f"{BASE}/organizations/{ORG_SLUG}", headers=hdr(token))
        if r.status_code == 200:
            org_id = r.json()["id"]
            print(f"  ~ re-used org_id: {org_id}")
        else:
            r = await c.post(
                f"{BASE}/organizations",
                headers=hdr(token),
                json={"name": "Feature Smoke Org", "slug": ORG_SLUG},
            )
            check("POST /organizations", r, 201)
            org_id = r.json()["id"]
            print(f"  → org_id: {org_id}")

        # ── Subscribe to Pro (so plan features apply) ─────────────────────
        print("\n=== Subscribe to Pro ===")
        # Get plan list
        r = await c.get(f"{BASE}/billing/plans", headers=hdr(token, org_id))
        plans = {p["slug"]: p["id"] for p in r.json().get("plans", [])}
        pro_id = plans.get("pro")
        print(f"  → pro plan_id: {pro_id}")

        r = await c.post(
            f"{BASE}/billing/subscribe",
            headers=hdr(token, org_id),
            json={"planId": pro_id, "billingCycle": "monthly"},
        )
        if r.status_code in (200, 201):
            print(f"  ✓ [{r.status_code}] subscribed to pro")
        else:
            print(f"  ~ [{r.status_code}] subscribe (may already be subscribed)")

        # ── Feature list (public) ─────────────────────────────────────────
        print("\n=== Features ===")
        r = await c.get(f"{BASE}/features", headers=hdr(token))
        check("GET  /features (public list)", r, 200)
        initial_count = r.json().get("total", 0)
        print(f"  → {initial_count} existing features")

        # ── Create feature ────────────────────────────────────────────────
        print("\n=== Admin: Create Feature ===")
        r = await c.post(
            f"{BASE}/admin/features",
            headers=hdr(token, org_id),
            json={
                "key": "smoke.advanced_analytics",
                "name": "Advanced Analytics",
                "description": "Smoke test feature",
                "module": "analytics",
            },
        )
        if r.status_code == 409:
            print(f"  ~ [409] feature already exists — re-using")
            # Re-use: fetch by listing
            r2 = await c.get(f"{BASE}/features", headers=hdr(token))
            feats = {f["key"]: f["id"] for f in r2.json().get("features", [])}
            feature_id = feats.get("smoke.advanced_analytics")
        else:
            check("POST /admin/features", r, 201)
            feature_id = r.json().get("id")

        print(f"  → feature_id: {feature_id}")

        # ── Assign feature to Pro plan ────────────────────────────────────
        print("\n=== Admin: Assign to Plan ===")
        r = await c.post(
            f"{BASE}/admin/plans/{pro_id}/features",
            headers=hdr(token, org_id),
            json={"featureId": feature_id, "limitValue": 100},
        )
        check("POST /admin/plans/{id}/features", r, 201)
        if r.status_code == 201:
            pf = r.json()
            print(f"  → assigned: {pf.get('featureKey')} limit={pf.get('limitValue')}")

        # ── Check feature (should be enabled via plan) ────────────────────
        print("\n=== Feature Check — via plan ===")
        r = await c.get(
            f"{BASE}/features/check?keys=smoke.advanced_analytics",
            headers=hdr(token, org_id),
        )
        check("GET  /features/check (plan)", r, 200)
        if r.status_code == 200:
            result = r.json()["results"].get("smoke.advanced_analytics", {})
            print(f"  → enabled={result.get('enabled')}, limit={result.get('limit')}")

        # ── Grant org override (increase limit to 999) ────────────────────
        print("\n=== Admin: Grant Override ===")
        r = await c.post(
            f"{BASE}/admin/organizations/{org_id}/feature-overrides",
            headers=hdr(token, org_id),
            json={
                "featureId": feature_id,
                "enabled": True,
                "limitValue": 999,
                "reason": "Enterprise deal — smoke test",
                "expiresAt": None,
            },
        )
        check("POST /admin/organizations/{id}/feature-overrides", r, 201)
        override_id = None
        if r.status_code == 201:
            override_id = r.json().get("id")
            print(f"  → override_id: {override_id}, limit={r.json().get('limitValue')}")

        # ── Check feature (should reflect override limit) ─────────────────
        print("\n=== Feature Check — after override ===")
        r = await c.get(
            f"{BASE}/features/check?keys=smoke.advanced_analytics",
            headers=hdr(token, org_id),
        )
        check("GET  /features/check (override)", r, 200)
        if r.status_code == 200:
            result = r.json()["results"].get("smoke.advanced_analytics", {})
            print(f"  → enabled={result.get('enabled')}, limit={result.get('limit')}")

        # ── Check multiple keys at once ───────────────────────────────────
        print("\n=== Multi-key Check ===")
        r = await c.get(
            f"{BASE}/features/check?keys=smoke.advanced_analytics&keys=nonexistent.feature",
            headers=hdr(token, org_id),
        )
        check("GET  /features/check (multi-key)", r, 200)
        if r.status_code == 200:
            results = r.json().get("results", {})
            for k, v in results.items():
                print(f"  → {k}: enabled={v.get('enabled')}, limit={v.get('limit')}")

        # ── Delete override ───────────────────────────────────────────────
        if override_id:
            print("\n=== Admin: Delete Override ===")
            r = await c.delete(
                f"{BASE}/admin/organizations/{org_id}/feature-overrides/{override_id}",
                headers=hdr(token, org_id),
            )
            check("DELETE /admin/organizations/{id}/feature-overrides/{fid}", r, 204)

            # ── Check feature (should fall back to plan limit) ────────────
            print("\n=== Feature Check — after override removed ===")
            r = await c.get(
                f"{BASE}/features/check?keys=smoke.advanced_analytics",
                headers=hdr(token, org_id),
            )
            check("GET  /features/check (post-delete fallback)", r, 200)
            if r.status_code == 200:
                result = r.json()["results"].get("smoke.advanced_analytics", {})
                print(f"  → enabled={result.get('enabled')}, limit={result.get('limit')}")

        print("\n=== Features smoke test complete ===\n")


if __name__ == "__main__":
    asyncio.run(main())
