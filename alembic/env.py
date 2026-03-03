"""
Alembic environment configuration.

Supports async migrations using the SQLAlchemy asyncpg driver.
Run migrations with:
    uv run alembic upgrade head
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.core.database import Base  # noqa: F401

# ── Import ALL models so Alembic autogenerate detects every table ──────────
# Order matches dependency graph: independent tables first, FKs after.

# Module 2: Auth
from app.modules.auth.models import (  # noqa: F401
    User,
    Session,
    VerificationToken,
    TwoFactorBackupCode,
    UserOAuthAccount,
)

# Module 1: Tenancy (depends on User)
from app.modules.tenancy.models import (  # noqa: F401
    Organization,
    OrganizationDomain,
    OrganizationUser,
    Invitation,
)

# Module 3: RBAC (depends on Organization, OrganizationUser)
from app.modules.rbac.models import (  # noqa: F401
    Role,
    Permission,
    RolePermission,
    OrganizationUserRole,
)

# Module 4: Billing
from app.modules.billing.models import (  # noqa: F401
    SubscriptionPlan,
    Subscription,
    Invoice,
    PaymentMethod,
)

# Module 5: Features (depends on SubscriptionPlan, Organization)
from app.modules.features.models import (  # noqa: F401
    Feature,
    PlanFeature,
    OrganizationFeatureOverride,
)

# Module 6: Audit
from app.modules.audit.models import AuditLog  # noqa: F401

# Module 7: Security
from app.modules.security.models import LoginAttempt, BlockedIP  # noqa: F401

# Module 8: API Management
from app.modules.api_management.models import (  # noqa: F401
    APIKey,
    Webhook,
    WebhookDelivery,
)

# Module 9: Notifications
from app.modules.notifications.models import (  # noqa: F401
    Notification,
    NotificationPreference,
)

# Module 10: Files
from app.modules.files.models import File  # noqa: F401

# Module 11: System
from app.modules.system.models import SystemSetting  # noqa: F401

# Module 12: Agents (depends on Organization, User)
from app.modules.agents.models import (  # noqa: F401
    Agent,
    AgentPhoneNumber,
    CallLog,
)

# ── Alembic Config object ──────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from app settings (honours .env file)
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)

target_metadata = Base.metadata


# ── Offline migrations (generate SQL without running it) ──────────────────
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migrations (connect to DB and apply) ────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

