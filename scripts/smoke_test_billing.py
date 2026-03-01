#!/usr/bin/env python3
"""
Day 7 Billing smoke test.

Tests all billing endpoints against the live server.
Requires the server to be running at localhost:8000.
"""

import asyncio
import httpx

BASE = "http://localhost:8000"


def ok(label: str, status: int, expected: int, body: dict | None = None) -> None:
    mark = "✓" if status == expected else "✗"
    print(f"  {mark} [{status}] {label}")
    if status != expected and body:
        # Show first 200 chars of error
        import json
        snippet = json.dumps(body)[:250]
        print(f"      {snippet}")


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as c:

        # ── Login ─────────────────────────────────────────────────────────
        print("\n=== Auth ===")
        r = await c.post(
            "/api/v1/auth/login",
            json={"email": "admin@test.com", "password": "TestPass123!"},
        )
        ok("POST /auth/login", r.status_code, 200)
        assert r.status_code == 200, f"Login failed: {r.text}"
        token = r.json()["accessToken"]
        auth = {"Authorization": f"Bearer {token}"}

        # ── Org context ───────────────────────────────────────────────────
        print("\n=== Setup Org ===")
        r = await c.post(
            "/api/v1/organizations",
            json={"name": "Billing Test Org", "slug": "billing-test-org-001"},
            headers=auth,
        )
        if r.status_code == 409:
            r = await c.get("/api/v1/organizations/billing-test-org-001", headers=auth)
        ok("GET org", r.status_code, 200)
        org_id = r.json()["id"]
        org_h = {**auth, "X-Organization-ID": org_id}
        print(f"  → org_id: {org_id}")

        # ── Plans (public — no auth needed) ───────────────────────────────
        print("\n=== Plans ===")
        r = await c.get("/api/v1/billing/plans")
        ok("GET  /billing/plans (public)", r.status_code, 200)
        plans = r.json().get("plans", [])
        print(f"  → {len(plans)} plans returned")
        plan_id = next((p["id"] for p in plans if p["slug"] == "pro"), plans[0]["id"] if plans else None)
        assert plan_id, "No plans found — run seed_plans.py first"

        r = await c.get(f"/api/v1/billing/plans/{plan_id}")
        ok("GET  /billing/plans/{id}", r.status_code, 200)

        # ── Admin: Create plan ─────────────────────────────────────────────
        r = await c.post(
            "/api/v1/billing/plans",
            json={
                "name": "Smoke Test Plan",
                "slug": "smoke-test-plan-001",
                "priceMonthly": "9.99",
                "currency": "USD",
                "trialDays": 7,
                "displayOrder": 99,
            },
            headers=auth,
        )
        ok("POST /billing/plans (admin)", r.status_code, 201)
        test_plan_id = r.json().get("id")

        if test_plan_id:
            r = await c.patch(
                f"/api/v1/billing/plans/{test_plan_id}",
                json={"description": "Updated by smoke test"},
                headers=auth,
            )
            ok("PATCH /billing/plans/{id}", r.status_code, 200)

            r = await c.delete(f"/api/v1/billing/plans/{test_plan_id}", headers=auth)
            ok("DELETE /billing/plans/{id}", r.status_code, 204)

        # ── Subscribe ─────────────────────────────────────────────────────
        print("\n=== Subscriptions ===")
        r = await c.post(
            "/api/v1/billing/subscribe",
            json={"planId": plan_id, "billingCycle": "monthly"},
            headers=org_h,
        )
        ok("POST /billing/subscribe", r.status_code, 201)
        sub = r.json()
        print(f"  → status: {sub.get('status')}, plan: {sub.get('plan', {}).get('slug')}")

        r = await c.get("/api/v1/billing/subscription", headers=org_h)
        ok("GET  /billing/subscription", r.status_code, 200)

        r = await c.get("/api/v1/billing/subscriptions", headers=org_h)
        ok("GET  /billing/subscriptions", r.status_code, 200)
        print(f"  → {len(r.json().get('subscriptions', []))} subscription(s) in history")

        # ── Invoices ──────────────────────────────────────────────────────
        print("\n=== Invoices ===")
        r = await c.get("/api/v1/billing/invoices", headers=org_h)
        ok("GET  /billing/invoices", r.status_code, 200)
        invoices = r.json().get("invoices", [])
        print(f"  → {len(invoices)} invoice(s)")

        if invoices:
            inv_id = invoices[0]["id"]
            r = await c.get(f"/api/v1/billing/invoices/{inv_id}", headers=org_h)
            ok("GET  /billing/invoices/{id}", r.status_code, 200)

        # ── Payment methods ───────────────────────────────────────────────
        print("\n=== Payment Methods ===")
        r = await c.get("/api/v1/billing/payment-methods", headers=org_h)
        ok("GET  /billing/payment-methods", r.status_code, 200)

        r = await c.post(
            "/api/v1/billing/payment-methods",
            json={
                "externalPaymentMethodId": "pm_test_smoke",
                "type": "card",
                "provider": "stripe",
                "lastFour": "4242",
                "cardBrand": "visa",
                "expiresMonth": 12,
                "expiresYear": 2027,
                "setAsDefault": True,
            },
            headers=org_h,
        )
        ok("POST /billing/payment-methods", r.status_code, 201)
        pm_id = r.json().get("id")

        if pm_id:
            r = await c.put(
                f"/api/v1/billing/payment-methods/{pm_id}/default",
                headers=org_h,
            )
            ok("PUT  /billing/payment-methods/{id}/default", r.status_code, 200)

        # ── Cancel subscription ───────────────────────────────────────────
        print("\n=== Cancel ===")
        r = await c.post(
            "/api/v1/billing/cancel",
            json={"reason": "Smoke test cleanup", "atPeriodEnd": False},
            headers=org_h,
        )
        ok("POST /billing/cancel", r.status_code, 200)
        print(f"  → status after cancel: {r.json().get('status')}")

        # ── Stripe webhook (test event) ───────────────────────────────────
        print("\n=== Webhooks ===")
        import json as _json
        payload = _json.dumps({
            "type": "invoice.paid",
            "data": {"object": {"id": "in_test", "subscription": "sub_test"}},
        }).encode()
        r = await c.post(
            "/api/v1/billing/webhooks/stripe",
            content=payload,
            headers={"content-type": "application/json"},
        )
        ok("POST /billing/webhooks/stripe", r.status_code, 200)

        r = await c.post(
            "/api/v1/billing/webhooks/razorpay",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
        ok("POST /billing/webhooks/razorpay", r.status_code, 200)

        print("\n=== Billing smoke test complete ===\n")


if __name__ == "__main__":
    asyncio.run(main())
