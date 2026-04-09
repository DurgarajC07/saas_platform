"""
Import every ORM model so the SQLAlchemy mapper registry is fully populated.

Import this module early in any script, CLI, or test that creates a database
session. Without it, cross-module string-based relationship references (e.g.
User → "OrganizationUser") fail with a KeyError during mapper configuration.

Usage::

    from app.core import all_models  # noqa: F401
"""

# Auth
from app.modules.auth.models import (  # noqa: F401
    Session,
    TwoFactorBackupCode,
    User,
    UserOAuthAccount,
    VerificationToken,
)

# Tenancy
from app.modules.tenancy.models import (  # noqa: F401
    Invitation,
    Organization,
    OrganizationDomain,
    OrganizationUser,
)

# RBAC
from app.modules.rbac.models import (  # noqa: F401
    OrganizationUserRole,
    Permission,
    Role,
    RolePermission,
)

# Billing
from app.modules.billing.models import (  # noqa: F401
    Invoice,
    PaymentMethod,
    Subscription,
    SubscriptionPlan,
)

# Features
from app.modules.features.models import (  # noqa: F401
    Feature,
    OrganizationFeatureOverride,
    PlanFeature,
)

# Audit
from app.modules.audit.models import AuditLog  # noqa: F401

# Security
from app.modules.security.models import BlockedIP, LoginAttempt  # noqa: F401

# API Management
from app.modules.api_management.models import (  # noqa: F401
    APIKey,
    Webhook,
    WebhookDelivery,
)

# Notifications
from app.modules.notifications.models import (  # noqa: F401
    Notification,
    NotificationPreference,
)

# Files
from app.modules.files.models import File  # noqa: F401

# System
from app.modules.system.models import SystemSetting  # noqa: F401

# Agents
from app.modules.agents.models import (  # noqa: F401
    Agent,
    AgentPhoneNumber,
    CallLog,
    KnowledgeBaseDocument,
)
