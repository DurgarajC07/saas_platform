#!/usr/bin/env python3
"""
Day 6 RBAC smoke test script.

Tests all 10 RBAC endpoints using httpx.
"""

import asyncio
import httpx

BASE = "http://localhost:8000"
HEADERS_JSON = {"Content-Type": "application/json"}


def ok(label: str, status: int, expected: int, body: dict) -> None:
    mark = "✓" if status == expected else "✗"
    print(f"  {mark} [{status}] {label}")
    if status != expected:
        print(f"      Response: {body}")


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as client:

        # ── 1. Login ──────────────────────────────────────────────────────
        print("\n=== Auth ===")
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@test.com", "password": "TestPass123!"},
        )
        ok("POST /auth/login", r.status_code, 200, r.json())
        token = r.json().get("accessToken", "")
        assert token, "Login failed — cannot continue"
        auth = {"Authorization": f"Bearer {token}"}

        # ── 2. Create org (to get an org_id) ──────────────────────────────
        print("\n=== Setup Org ===")
        r = await client.post(
            "/api/v1/organizations",
            json={"name": "RBAC Test Org", "slug": "rbac-test-org-001"},
            headers=auth,
        )
        ok("POST /organizations", r.status_code, 201, r.json())
        if r.status_code == 409:
            # Already exists — fetch it
            r = await client.get("/api/v1/organizations/rbac-test-org-001", headers=auth)
        org_id = r.json().get("id") or r.json().get("data", {}).get("id")
        assert org_id, f"Could not get org_id from {r.json()}"
        print(f"  → org_id: {org_id}")
        org_headers = {**auth, "X-Organization-ID": org_id}

        # Get membership id for member role tests
        r = await client.get(f"/api/v1/organizations/{org_id}/members", headers=org_headers)
        members = r.json()
        member_items = (
            members.get("members")
            or members.get("data", {}).get("members")
            or []
        )
        member_id = member_items[0]["id"] if member_items else None
        print(f"  → member_id: {member_id}")

        # ── 3. RBAC endpoints ─────────────────────────────────────────────
        print("\n=== RBAC Tests ===")

        # LIST ROLES
        r = await client.get("/api/v1/rbac/roles", headers=org_headers)
        ok("GET  /rbac/roles", r.status_code, 200, r.json())
        roles = r.json().get("roles", [])
        print(f"  → {len(roles)} roles visible")

        # CREATE ROLE
        r = await client.post(
            "/api/v1/rbac/roles",
            json={"name": "test-editor", "displayName": "Test Editor", "priority": 5},
            headers=org_headers,
        )
        ok("POST /rbac/roles", r.status_code, 201, r.json())
        new_role_id = r.json().get("id")

        if not new_role_id:
            print("  → Skipping role mutation tests (create failed)")
        else:
            # UPDATE ROLE
            r = await client.patch(
                f"/api/v1/rbac/roles/{new_role_id}",
                json={"description": "Updated by smoke test"},
                headers=org_headers,
            )
            ok("PATCH /rbac/roles/{id}", r.status_code, 200, r.json())

            # LIST PERMISSIONS (catalogue)
            r = await client.get("/api/v1/rbac/permissions", headers=org_headers)
            ok("GET  /rbac/permissions", r.status_code, 200, r.json())
            all_perm_groups = r.json().get("groups", [])
            total_perms = r.json().get("total", 0)
            print(f"  → {total_perms} permissions in {len(all_perm_groups)} modules")

            # Grab a few permission IDs for assignment
            perm_ids = []
            for g in all_perm_groups:
                for p in g.get("permissions", [])[:2]:
                    perm_ids.append(p["id"])
                if len(perm_ids) >= 4:
                    break

            # LIST ROLE PERMISSIONS (before set)
            r = await client.get(
                f"/api/v1/rbac/roles/{new_role_id}/permissions",
                headers=org_headers,
            )
            ok("GET  /rbac/roles/{id}/permissions", r.status_code, 200, r.json())

            # SET ROLE PERMISSIONS (bulk PUT)
            r = await client.put(
                f"/api/v1/rbac/roles/{new_role_id}/permissions",
                json={"permissionIds": perm_ids},
                headers=org_headers,
            )
            ok("PUT  /rbac/roles/{id}/permissions", r.status_code, 200, r.json())
            assigned_perms = r.json().get("permissions", [])
            print(f"  → {len(assigned_perms)} permissions assigned")

            # MEMBER ROLE TESTS
            if member_id:
                # GET member roles (before assignment)
                r = await client.get(
                    f"/api/v1/rbac/members/{member_id}/roles",
                    headers=org_headers,
                )
                ok("GET  /rbac/members/{id}/roles", r.status_code, 200, r.json())
                current_roles = r.json().get("roles", [])
                print(f"  → member has {len(current_roles)} role(s) currently")

                # ASSIGN role to member
                r = await client.put(
                    f"/api/v1/rbac/members/{member_id}/roles/{new_role_id}",
                    headers=org_headers,
                )
                ok("PUT  /rbac/members/{id}/roles/{id}", r.status_code, 200, r.json())

                # REVOKE role from member
                r = await client.delete(
                    f"/api/v1/rbac/members/{member_id}/roles/{new_role_id}",
                    headers=org_headers,
                )
                ok("DELETE /rbac/members/{id}/roles/{id}", r.status_code, 204, r.json() if r.content else {})

            # DELETE ROLE (cleanup)
            r = await client.delete(
                f"/api/v1/rbac/roles/{new_role_id}",
                headers=org_headers,
            )
            ok("DELETE /rbac/roles/{id}", r.status_code, 204, {})

        print("\n=== Smoke test complete ===\n")


if __name__ == "__main__":
    asyncio.run(main())
