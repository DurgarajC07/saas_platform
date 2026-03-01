#!/usr/bin/env python
"""
Interactive CLI to create a platform superuser (is_platform_admin=True).

Reads credentials from CLI args, environment variables, or prompts
interactively.  Password is hashed with Argon2id.

Usage:
    # interactive prompts
    uv run python scripts/create_superuser.py

    # non-interactive (useful in CI/CD)
    SUPERUSER_EMAIL=admin@example.com \
    SUPERUSER_PASSWORD=s3cr3t \
    SUPERUSER_FIRST_NAME=Platform \
    SUPERUSER_LAST_NAME=Admin \
    uv run python scripts/create_superuser.py

    # or via args
    uv run python scripts/create_superuser.py \
        --email admin@example.com \
        --password s3cr3t \
        --first-name Platform \
        --last-name Admin
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import all_models  # noqa: F401 — populate SQLAlchemy mapper registry
from app.core.database import create_engine, create_session_factory
from app.core.security.hashing import hash_password
from app.modules.auth.models import User


# ── Argument parsing ──────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a platform superuser (is_platform_admin=True)."
    )
    parser.add_argument("--email",      default=None, help="Superuser email address")
    parser.add_argument("--password",   default=None, help="Plaintext password (will be hashed)")
    parser.add_argument("--first-name", default=None, dest="first_name")
    parser.add_argument("--last-name",  default=None, dest="last_name")
    return parser.parse_args()


def _prompt(prompt: str, default: str | None = None, secret: bool = False) -> str:
    """Prompt user for input; fall back to *default* if provided."""
    if default:
        return default
    while True:
        if secret:
            value = getpass.getpass(prompt)
        else:
            value = input(prompt).strip()
        if value:
            return value
        print("  Value cannot be empty, please try again.")


def _confirm_password(initial: str) -> str:
    while True:
        confirm = getpass.getpass("Confirm password: ")
        if confirm == initial:
            return confirm
        print("  Passwords do not match, try again.")


# ── Core logic ────────────────────────────────────────────────────────────

async def create_superuser(session: AsyncSession, email: str, password: str, first_name: str, last_name: str) -> None:
    email = email.lower().strip()

    existing = await session.execute(select(User).where(User.email == email))
    existing_user = existing.scalar_one_or_none()
    if existing_user:
        if existing_user.is_platform_admin:
            print(f"Platform admin with email {email!r} already exists — no changes made.")
        else:
            # Upgrade existing regular user to platform admin
            existing_user.is_platform_admin = True
            existing_user.updated_at = datetime.now(UTC)
            await session.commit()
            print(f"Existing user {email!r} upgraded to platform admin.")
        return

    now = datetime.now(UTC)
    user = User(
        id=uuid4(),
        email=email,
        password_hash=hash_password(password),
        first_name=first_name,
        last_name=last_name,
        display_name=f"{first_name} {last_name}".strip() or email,
        is_platform_admin=True,
        is_active=True,
        email_verified=True,
        email_verified_at=now,
        password_changed_at=now,
        timezone="UTC",
        locale="en",
        preferences={},
        metadata_={},
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    await session.commit()
    print(f"Platform admin created successfully.")
    print(f"  ID    : {user.id}")
    print(f"  Email : {user.email}")
    print(f"  Name  : {user.display_name}")


async def main() -> None:
    args = parse_args()

    email = (
        args.email
        or os.environ.get("SUPERUSER_EMAIL")
        or _prompt("Email address: ")
    )
    password_raw = (
        args.password
        or os.environ.get("SUPERUSER_PASSWORD")
        or _prompt("Password: ", secret=True)
    )
    # Only confirm when running interactively (no env var / flag)
    if not args.password and not os.environ.get("SUPERUSER_PASSWORD"):
        _confirm_password(password_raw)

    first_name = (
        args.first_name
        or os.environ.get("SUPERUSER_FIRST_NAME")
        or _prompt("First name [Admin]: ") or "Admin"
    )
    last_name = (
        args.last_name
        or os.environ.get("SUPERUSER_LAST_NAME")
        or _prompt("Last name [User]: ") or "User"
    )

    settings = get_settings()
    engine = create_engine(settings)
    factory = create_session_factory(engine)

    async with factory() as session:
        await create_superuser(session, email, password_raw, first_name, last_name)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
