#!/usr/bin/env python
"""
Seed the RBAC system roles (owner / admin / member / viewer) and grant each
one a default permission set.

Why this exists
----------------
Without this script, no organization member — only a platform superuser
created via ``create_superuser.py`` — can pass any ``require(...)`` permission
check anywhere in the app. `TenancyService.create_organization()` already
looks up a system role named "owner" and assigns it to every org creator
(`app/modules/tenancy/service.py`), but nothing in this repository ever
created that role or granted it any permissions — its own comment says
"best-effort — OK if role not seeded yet", i.e. it was designed to fail
silently rather than guarantee the role exists. Run this once per
environment (idempotent — safe to re-run) after ``seed_permissions.py``.

Usage:
    uv run python scripts/seed_permissions.py   # must run first
    uv run python scripts/seed_roles.py

Default authorization model
----------------------------
Four system roles (``organization_id = NULL``, ``is_system_role = True``,
visible to every org per ``RoleRepository.list_by_org``'s system-role OR
clause), ranked to match ``TenancyService._ROLE_RANK`` (owner=4 > admin=3 >
member=2 > viewer=1):

  owner   — every permission except the platform-only set below. Can delete
            the organization, change role→permission grants, and cancel the
            subscription.
  admin   — everything owner has EXCEPT: deleting the organization itself,
            regranting role permissions (prevents an admin from editing a
            role's grants to escalate themselves), and cancelling the
            subscription. Day-to-day org administration.
  member  — can create/read/update/list the org's own working data (agents,
            calls, knowledge bases, tools, files, their own notification
            preferences) but cannot manage billing, tenancy membership,
            security settings, API keys/webhooks, audit logs, or RBAC
            roles, and cannot delete most resources.
  viewer  — read-only: *.read / *.list / *.download actions on business
            data only (agents, calls, billing, org/member info, files,
            notifications) — no visibility into audit logs, security
            settings, or API keys/webhooks, and no RBAC/system access.

A fixed set of permissions is never granted to ANY org-level role, because
they govern platform-wide entities an org shouldn't control about itself:
defining subscription plans, defining what features exist, assigning
features to plans, granting an org extra features via override, and
platform-wide system settings. Platform superusers reach these via the
``is_platform_admin`` bypass in ``RBACService.require_permission()``, not
through a role grant.

This is a reasonable, conservative default — not a requirement handed down
by product. If your authorization model should differ (e.g. "member" should
be able to manage billing), edit the rule sets below and re-run; the script
is idempotent (``RolePermissionRepository.set_permissions`` replaces a
role's grants atomically on every run).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to path so app imports work when run directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime, UTC
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import all_models  # noqa: F401 — populate SQLAlchemy mapper registry
from app.core.database import create_engine, create_session_factory
from app.modules.rbac.models import Permission, Role
from app.modules.rbac.repository import RolePermissionRepository

# ── Role definitions ────────────────────────────────────────────────────────
# Priority mirrors app/modules/tenancy/service.py::_ROLE_RANK exactly.
ROLE_DEFS: list[dict] = [
    {"name": "owner", "display_name": "Owner", "priority": 4,
     "description": "Full control of the organization, including billing and role management."},
    {"name": "admin", "display_name": "Admin", "priority": 3,
     "description": "Manages the organization day-to-day; cannot delete the org, cancel the subscription, or regrant role permissions."},
    {"name": "member", "display_name": "Member", "priority": 2,
     "description": "Operates the org's working data (agents, calls, files); no billing, security, or RBAC management."},
    {"name": "viewer", "display_name": "Viewer", "priority": 1,
     "description": "Read-only access to business data; no audit, security, API-management, or RBAC visibility."},
]

# ── Permissions never granted to any org-level system role ─────────────────
# These govern platform-wide entities, not something an org controls about
# itself. Platform superusers reach them via the is_platform_admin bypass.
PLATFORM_ONLY: set[tuple[str, str, str]] = {
    ("billing", "plan", "create"),
    ("billing", "plan", "update"),
    ("billing", "plan", "delete"),
    ("features", "feature", "create"),
    ("features", "feature", "update"),
    ("features", "feature", "delete"),
    ("features", "plan_feature", "manage"),
    ("features", "org_override", "create"),
    ("features", "org_override", "update"),
    ("features", "org_override", "delete"),
    ("system", "setting", "update"),
    # Account impersonation is platform-admin territory, not even an org
    # owner's call to make by default — nothing currently wires this to a
    # route guard, but it's excluded from every org role as a safe default.
    ("auth", "user", "impersonate"),
}

# Owner-exclusive even within the org: admin does not get these.
OWNER_ONLY: set[tuple[str, str, str]] = {
    ("tenancy", "organization", "delete"),
    ("rbac", "role_permission", "grant"),
    ("rbac", "role_permission", "revoke"),
    ("billing", "subscription", "cancel"),
}

# Modules member/viewer never get any permission from (admin-and-up only).
# "auth" is here too: auth.user.* governs platform user-account management
# (create/update/delete/list/impersonate *any* user, not just org members —
# that's tenancy.member.*), which is sensitive even though nothing currently
# wires it to a route guard (grepped: no `require("auth.*")` call exists
# anywhere yet) — seeding it narrowly now avoids a silent privilege
# escalation the day someone does wire it up.
ADMIN_AND_UP_ONLY_MODULES: set[str] = {"auth", "rbac", "security", "api_management", "audit", "system"}

# Specific permissions that stay admin-and-up even though their module
# (agents) is otherwise open to member: overriding the LLM model config and
# exporting call transcripts (which may contain PII) are elevated actions,
# not everyday agent operation.
ADMIN_AND_UP_ONLY_PERMS: set[tuple[str, str, str]] = {
    ("agents", "admin", "models"),
    ("agents", "call", "export"),
}


# Within the modules member IS allowed into, these mutating actions are
# still admin-and-up only (member can create/read/update/list its own
# working data, but not delete most things or manage tenancy/billing).
MEMBER_EXCLUDED_ACTIONS: set[str] = {"delete", "revoke", "remove", "manage", "cancel", "impersonate", "verify"}
# Specific allowances inside that exclusion — deleting your OWN notification
# or your own KB document/call-log upload is a normal user action, not an
# administrative one.
MEMBER_ALLOWED_OVERRIDES: set[tuple[str, str, str]] = {
    ("notifications", "notification", "delete"),
    ("agents", "knowledge_base", "delete"),
}
# Modules member only gets read/list from, even though the module itself
# isn't admin-and-up-only (member shouldn't manage tenancy or billing, but
# should be able to see them).
MEMBER_READ_ONLY_MODULES: set[str] = {"tenancy", "billing", "features"}

READ_ACTIONS: set[str] = {"read", "list", "download"}
# Modules viewer has no visibility into at all (on top of
# ADMIN_AND_UP_ONLY_MODULES, which already excludes rbac/security/
# api_management/audit/system for everyone below admin).
VIEWER_EXCLUDED_MODULES: set[str] = set()  # nothing further excluded today


def _perm_key(p: Permission) -> tuple[str, str, str]:
    return (p.module, p.resource, p.action)


def _build_role_grants(all_perms: list[Permission]) -> dict[str, list[Permission]]:
    org_level = [p for p in all_perms if _perm_key(p) not in PLATFORM_ONLY]

    owner = list(org_level)

    admin = [p for p in org_level if _perm_key(p) not in OWNER_ONLY]

    member = [
        p
        for p in admin
        if _perm_key(p) not in ADMIN_AND_UP_ONLY_PERMS
        and p.module not in ADMIN_AND_UP_ONLY_MODULES
        and (
            p.module not in MEMBER_READ_ONLY_MODULES
            or p.action in READ_ACTIONS
        )
        and (
            p.action not in MEMBER_EXCLUDED_ACTIONS
            or _perm_key(p) in MEMBER_ALLOWED_OVERRIDES
        )
    ]

    viewer = [
        p
        for p in admin
        if p.module not in ADMIN_AND_UP_ONLY_MODULES
        and p.module not in VIEWER_EXCLUDED_MODULES
        and p.action in READ_ACTIONS
    ]

    return {"owner": owner, "admin": admin, "member": member, "viewer": viewer}


async def _get_or_create_role(session: AsyncSession, role_def: dict) -> Role:
    existing = await session.execute(
        select(Role).where(
            Role.name == role_def["name"],
            Role.is_system_role.is_(True),
        )
    )
    role = existing.scalar_one_or_none()
    if role:
        return role

    now = datetime.now(UTC)
    role = Role(
        id=uuid4(),
        name=role_def["name"],
        display_name=role_def["display_name"],
        description=role_def["description"],
        organization_id=None,
        is_system_role=True,
        is_default=(role_def["name"] == "member"),
        priority=role_def["priority"],
        created_at=now,
        updated_at=now,
    )
    session.add(role)
    await session.flush()
    return role


async def seed_roles(session: AsyncSession) -> None:
    perm_result = await session.execute(select(Permission))
    all_perms = list(perm_result.scalars().all())
    if not all_perms:
        print(
            "No permissions found — run scripts/seed_permissions.py first. Aborting."
        )
        return

    grants = _build_role_grants(all_perms)
    role_perm_repo = RolePermissionRepository(session)

    for role_def in ROLE_DEFS:
        role = await _get_or_create_role(session, role_def)
        perm_ids = [p.id for p in grants[role_def["name"]]]
        await role_perm_repo.set_permissions(role.id, perm_ids)
        print(
            f"Role '{role_def['name']}' (id={role.id}): "
            f"{len(perm_ids)} permissions granted."
        )

    await session.commit()
    print("Done. Re-run any time to re-sync grants with the rule sets above.")


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_roles(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
