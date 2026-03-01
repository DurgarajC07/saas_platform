"""
Celery application instance.

Broker and result backend both use the application's Redis URL.
Configure via environment variables (mirrors settings); no hard-coded values.

Run a worker:
    celery -A app.core.celery_app worker --loglevel=info

Run with beat (for periodic tasks):
    celery -A app.core.celery_app worker --beat --loglevel=info
"""

from celery import Celery

from app.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "saas_platform",
    broker=_settings.REDIS_URL,
    backend=_settings.REDIS_URL,
    include=["app.tasks.webhook", "app.tasks.notifications"],
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
    # Result expiry
    result_expires=3600,
    # Routing — delivery tasks go to dedicated queues
    task_routes={
        "app.tasks.webhook.deliver_webhook": {"queue": "webhooks"},
        "app.tasks.notifications.dispatch_notification": {"queue": "notifications"},
    },
    task_default_queue="default",
)
