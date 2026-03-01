"""
Celery application instance.

Broker and result backend both use the application's Redis URL.
Configure via environment variables (mirrors settings); no hard-coded values.

Run a worker (all queues):
    celery -A app.core.celery_app worker --loglevel=info \\
        -Q default,webhooks,notifications,email,maintenance,storage,billing,exports

Run with beat (schedule + worker):
    celery -A app.core.celery_app worker --beat --loglevel=info
"""

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.config import get_settings

_settings = get_settings()

# ── Queue definitions ─────────────────────────────────────────────────────────

_default_exchange = Exchange("default", type="direct")

CELERY_QUEUES = (
    Queue("default",      _default_exchange, routing_key="default"),
    Queue("webhooks",     Exchange("webhooks",     type="direct"), routing_key="webhooks"),
    Queue("notifications",Exchange("notifications",type="direct"), routing_key="notifications"),
    Queue("email",        Exchange("email",        type="direct"), routing_key="email"),
    Queue("maintenance",  Exchange("maintenance",  type="direct"), routing_key="maintenance"),
    Queue("storage",      Exchange("storage",      type="direct"), routing_key="storage"),
    Queue("billing",      Exchange("billing",      type="direct"), routing_key="billing"),
    Queue("exports",      Exchange("exports",      type="direct"), routing_key="exports"),
)

# ── Beat schedule ─────────────────────────────────────────────────────────────

CELERY_BEAT_SCHEDULE = {
    # Cleanup tasks — run overnight to minimise DB load during business hours
    "cleanup-expired-tokens-daily": {
        "task": "app.tasks.maintenance.cleanup_expired_tokens",
        "schedule": crontab(hour=2, minute=0),
        "options": {"queue": "maintenance"},
    },
    "cleanup-expired-sessions-daily": {
        "task": "app.tasks.maintenance.cleanup_expired_sessions",
        "schedule": crontab(hour=3, minute=0),
        "options": {"queue": "maintenance"},
    },
    "cleanup-stale-login-attempts-weekly": {
        "task": "app.tasks.maintenance.cleanup_stale_login_attempts",
        "schedule": crontab(hour=4, minute=0, day_of_week="sunday"),
        "options": {"queue": "maintenance"},
    },
    "cleanup-deleted-files-daily": {
        "task": "app.tasks.maintenance.cleanup_deleted_files",
        "schedule": crontab(hour=5, minute=0),
        "options": {"queue": "storage"},
    },
    # Billing checks — every hour
    "check-subscription-expirations-hourly": {
        "task": "app.tasks.maintenance.check_subscription_expirations",
        "schedule": crontab(minute=0),  # top of every hour
        "options": {"queue": "billing"},
    },
    # Billing alerts — morning daily
    "send-billing-alerts-daily": {
        "task": "app.tasks.maintenance.send_billing_alerts",
        "schedule": crontab(hour=9, minute=0),
        "options": {"queue": "email"},
    },
}

# ── App instance ──────────────────────────────────────────────────────────────

celery_app = Celery(
    "saas_platform",
    broker=_settings.REDIS_URL,
    backend=_settings.REDIS_URL,
    include=[
        "app.tasks.webhook",
        "app.tasks.notifications",
        "app.tasks.files",
        "app.tasks.email",
        "app.tasks.maintenance",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Retry policy defaults
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Result expiry: 1 hour
    result_expires=3600,
    # Queues
    task_queues=CELERY_QUEUES,
    task_default_queue="default",
    # Routing
    task_routes={
        # Existing tasks
        "app.tasks.webhook.deliver_webhook": {"queue": "webhooks"},
        "app.tasks.notifications.dispatch_notification": {"queue": "notifications"},
        "app.tasks.files.delete_storage_object": {"queue": "storage"},
        # Email tasks
        "app.tasks.email.send_verification_email": {"queue": "email"},
        "app.tasks.email.send_invitation_email": {"queue": "email"},
        "app.tasks.email.send_password_reset_email": {"queue": "email"},
        # Maintenance tasks
        "app.tasks.maintenance.cleanup_expired_tokens": {"queue": "maintenance"},
        "app.tasks.maintenance.cleanup_expired_sessions": {"queue": "maintenance"},
        "app.tasks.maintenance.cleanup_stale_login_attempts": {"queue": "maintenance"},
        "app.tasks.maintenance.cleanup_deleted_files": {"queue": "storage"},
        "app.tasks.maintenance.check_subscription_expirations": {"queue": "billing"},
        "app.tasks.maintenance.send_billing_alerts": {"queue": "email"},
        "app.tasks.maintenance.export_audit_logs": {"queue": "exports"},
    },
    # Beat schedule
    beat_schedule=CELERY_BEAT_SCHEDULE,
)
