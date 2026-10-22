from celery import Celery

from app.core.config import get_settings

_s = get_settings()

celery_app = Celery("smartspend", broker=_s.redis_url, backend=_s.redis_url, include=["app.tasks"])
celery_app.conf.update(
    task_always_eager=_s.celery_task_always_eager,
    task_eager_propagates=False,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    beat_schedule={
        "notification-checks": {"task": "app.tasks.run_all_notification_checks", "schedule": 6 * 3600},
    },
)
