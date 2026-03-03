#!/usr/bin/env python
"""
Seed RBAC permissions into the database.

Creates one Permission record per (module, resource, action) triple across
all 11 application modules. Expect ~100 records after a full run.

Usage:
    uv run python scripts/seed_permissions.py
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
from app.modules.rbac.models import Permission

# ── Permission catalogue ───────────────────────────────────────────────────
# Format: (module, resource, action)
# action conventions: create | read | update | delete | list | export | manage
PERMISSIONS: list[tuple[str, str, str]] = [
    # ── Auth ───────────────────────────────────────────────────────────────
    ("auth", "user", "create"),
    ("auth", "user", "read"),
    ("auth", "user", "update"),
    ("auth", "user", "delete"),
    ("auth", "user", "list"),
    ("auth", "user", "impersonate"),
    ("auth", "session", "read"),
    ("auth", "session", "delete"),
    ("auth", "session", "list"),

    # ── Tenancy ────────────────────────────────────────────────────────────
    ("tenancy", "organization", "create"),
    ("tenancy", "organization", "read"),
    ("tenancy", "organization", "update"),
    ("tenancy", "organization", "delete"),
    ("tenancy", "organization", "list"),
    ("tenancy", "organization", "manage"),
    ("tenancy", "member", "invite"),
    ("tenancy", "member", "read"),
    ("tenancy", "member", "update"),
    ("tenancy", "member", "remove"),
    ("tenancy", "member", "list"),
    ("tenancy", "invitation", "create"),
    ("tenancy", "invitation", "read"),
    ("tenancy", "invitation", "revoke"),
    ("tenancy", "invitation", "list"),
    ("tenancy", "domain", "create"),
    ("tenancy", "domain", "read"),
    ("tenancy", "domain", "delete"),
    ("tenancy", "domain", "list"),
    ("tenancy", "domain", "verify"),

    # ── RBAC ──────────────────────────────────────────────────────────────
    ("rbac", "role", "create"),
    ("rbac", "role", "read"),
    ("rbac", "role", "update"),
    ("rbac", "role", "delete"),
    ("rbac", "role", "list"),
    ("rbac", "permission", "read"),
    ("rbac", "permission", "list"),
    ("rbac", "role_permission", "grant"),
    ("rbac", "role_permission", "revoke"),
    ("rbac", "user_role", "assign"),
    ("rbac", "user_role", "revoke"),
    ("rbac", "user_role", "list"),

    # ── Billing ───────────────────────────────────────────────────────────
    ("billing", "plan", "read"),
    ("billing", "plan", "list"),
    ("billing", "plan", "create"),
    ("billing", "plan", "update"),
    ("billing", "plan", "delete"),
    ("billing", "subscription", "create"),
    ("billing", "subscription", "read"),
    ("billing", "subscription", "update"),
    ("billing", "subscription", "cancel"),
    ("billing", "subscription", "list"),
    ("billing", "invoice", "read"),
    ("billing", "invoice", "list"),
    ("billing", "invoice", "export"),
    ("billing", "payment_method", "create"),
    ("billing", "payment_method", "read"),
    ("billing", "payment_method", "update"),
    ("billing", "payment_method", "delete"),
    ("billing", "payment_method", "list"),

    # ── Features ──────────────────────────────────────────────────────────
    ("features", "feature", "read"),
    ("features", "feature", "list"),
    ("features", "feature", "create"),
    ("features", "feature", "update"),
    ("features", "feature", "delete"),
    ("features", "plan_feature", "manage"),
    ("features", "org_override", "create"),
    ("features", "org_override", "read"),
    ("features", "org_override", "update"),
    ("features", "org_override", "delete"),
    ("features", "org_override", "list"),

    # ── Audit ─────────────────────────────────────────────────────────────
    ("audit", "log", "read"),
    ("audit", "log", "list"),
    ("audit", "log", "export"),

    # ── Security ──────────────────────────────────────────────────────────
    ("security", "login_attempt", "read"),
    ("security", "login_attempt", "list"),
    ("security", "blocked_ip", "create"),
    ("security", "blocked_ip", "read"),
    ("security", "blocked_ip", "update"),
    ("security", "blocked_ip", "delete"),
    ("security", "blocked_ip", "list"),

    # ── API Management ────────────────────────────────────────────────────
    ("api_management", "api_key", "create"),
    ("api_management", "api_key", "read"),
    ("api_management", "api_key", "update"),
    ("api_management", "api_key", "revoke"),
    ("api_management", "api_key", "list"),
    ("api_management", "webhook", "create"),
    ("api_management", "webhook", "read"),
    ("api_management", "webhook", "update"),
    ("api_management", "webhook", "delete"),
    ("api_management", "webhook", "list"),
    ("api_management", "webhook_delivery", "read"),
    ("api_management", "webhook_delivery", "list"),

    # ── Notifications ─────────────────────────────────────────────────────
    ("notifications", "notification", "read"),
    ("notifications", "notification", "list"),
    ("notifications", "notification", "delete"),
    ("notifications", "preference", "read"),
    ("notifications", "preference", "update"),

    # ── Files ─────────────────────────────────────────────────────────────
    ("files", "file", "create"),
    ("files", "file", "read"),
    ("files", "file", "update"),
    ("files", "file", "delete"),
    ("files", "file", "list"),
    ("files", "file", "download"),

    # ── System ────────────────────────────────────────────────────────────
    ("system", "setting", "read"),
    ("system", "setting", "update"),
    ("system", "setting", "list"),

    # ── Agents ────────────────────────────────────────────────────────────
    ("agents", "agent", "create"),
    ("agents", "agent", "read"),
    ("agents", "agent", "update"),
    ("agents", "agent", "delete"),
    ("agents", "agent", "list"),
    ("agents", "phone_number", "create"),
    ("agents", "phone_number", "read"),
    ("agents", "phone_number", "list"),
    ("agents", "knowledge_base", "create"),
    ("agents", "knowledge_base", "delete"),
    ("agents", "call_log", "create"),
    ("agents", "call_log", "read"),
    ("agents", "call_log", "list"),
    ("agents", "analytics", "read"),
]


def _build_permission_name(module: str, resource: str, action: str) -> str:
    return f"{module}.{resource}.{action}"


async def seed_permissions(session: AsyncSession) -> None:
    now = datetime.now(UTC)
    inserted = 0
    skipped = 0

    for module, resource, action in PERMISSIONS:
        name = _build_permission_name(module, resource, action)
        existing = await session.execute(
            select(Permission).where(Permission.name == name)
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        perm = Permission(
            id=uuid4(),
            name=name,
            display_name=f"{action.replace('_', ' ').title()} {resource.replace('_', ' ').title()}",
            module=module,
            resource=resource,
            action=action,
            created_at=now,
            updated_at=now,
        )
        session.add(perm)
        inserted += 1

    await session.commit()
    print(f"Permissions seeded: {inserted} inserted, {skipped} already existed.")
    print(f"Total permissions defined: {len(PERMISSIONS)}")


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_permissions(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
