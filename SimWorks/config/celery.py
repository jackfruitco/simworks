# config/celery.py
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("simworks")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps, then
# Load task modules from simcore.ai_v1
app.autodiscover_tasks()
app.autodiscover_tasks(packages=["simcore"], related_name="ai_v1.tasks.executors")

@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")
