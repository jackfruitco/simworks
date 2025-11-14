# config/celery.py
import os

from celery import Celery
from celery import signals
from simcore_ai_django.setup import configure_ai_clients, autodiscover_all
from simcore_ai.tracing import service_span_sync

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Ensure Django apps are loaded so AppConfig.ready() runs (triggers AI autodiscovery)
import django  # noqa: E402
django.setup()

app = Celery("simworks")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps
app.autodiscover_tasks()

@signals.worker_process_init.connect
def _ai_setup_for_worker(**_):
    # Runs in each worker child; ensures registries are populated in this process.
    with service_span_sync("celery.worker_process_init.ai_setup"):
        configure_ai_clients()
        autodiscover_all()

@signals.beat_init.connect
def _ai_setup_for_beat(**_):
    # If using Celery Beat, it may also need registries for scheduled tasks.
    with service_span_sync("celery.beat_init.ai_setup"):
        configure_ai_clients()
        autodiscover_all()

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
