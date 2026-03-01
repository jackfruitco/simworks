# config/celery.py
import os

from celery import Celery
from celery import signals
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("simworks")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps
app.autodiscover_tasks()

# Beat schedule for periodic tasks
app.conf.beat_schedule = {
    # Drain outbox every 15 seconds for reliable event delivery
    "drain-outbox-every-15-seconds": {
        "task": "apps.common.tasks.drain_outbox",
        "schedule": 15.0,  # seconds
    },
    # Clean up old delivered events daily at 3 AM
    "cleanup-old-outbox-events-daily": {
        "task": "apps.common.tasks.cleanup_delivered_events",
        "schedule": crontab(hour=3, minute=0),
        "kwargs": {"days_old": 7},
    },
    # Retry failed events every hour
    "retry-failed-outbox-events-hourly": {
        "task": "apps.common.tasks.retry_failed_events",
        "schedule": crontab(minute=30),  # At 30 minutes past each hour
    },
}

# @signals.worker_process_init.connect
# def _ai_setup_for_worker(**_):
#     # Runs in each worker child; ensures registries are populated in this process.
#     with service_span_sync("celery.worker_process_init.ai_setup"):
#         # configure_ai_clients()
#         autodiscover_all()
#
# @signals.beat_init.connect
# def _ai_setup_for_beat(**_):
#     # If using Celery Beat, it may also need registries for scheduled tasks.
#     with service_span_sync("celery.beat_init.ai_setup"):
#         # configure_ai_clients()
#         autodiscover_all()

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
