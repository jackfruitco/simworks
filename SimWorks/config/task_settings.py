"""Async/task execution settings (Django Tasks, channels, Celery, rate limits)."""

from __future__ import annotations

import os

from apps.common.utils.system import check_env

from .settings_parsers import int_from_env

TASKS = {
    "default": {
        "BACKEND": "orchestrai_django.backends.async_thread.AsyncThreadBackend",
    },
    "immediate": {
        "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
    },
}

DJANGO_TASKS_MAX_RETRIES = int_from_env("DJANGO_TASKS_MAX_RETRIES", default=3, minimum=0)
DJANGO_TASKS_RETRY_DELAY = int_from_env("DJANGO_TASKS_RETRY_DELAY", default=5, minimum=0)

REDIS_HOSTNAME = os.getenv("REDIS_HOSTNAME", "redis")
REDIS_PORT = 6379
REDIS_PASSWORD = check_env("REDIS_PASSWORD")
REDIS_BASE = f"redis://:{REDIS_PASSWORD}@{REDIS_HOSTNAME}:{REDIS_PORT}"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [f"{REDIS_BASE}/0"],
        },
    }
}

CELERY_BROKER_URL = f"{REDIS_BASE}/1"
CELERY_RESULT_BACKEND = f"{REDIS_BASE}/2"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_RESULT_ACCEPT_CONTENT = ["json"]  # Explicitly reject pickle in result backend
CELERY_TASK_TIME_LIMIT = int_from_env("CELERY_TASK_TIME_LIMIT", default=30, minimum=1)
CELERY_TASK_SOFT_TIME_LIMIT = int_from_env("CELERY_TASK_SOFT_TIME_LIMIT", default=25, minimum=1)
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

RATE_LIMIT_AUTH_REQUESTS = int_from_env("RATE_LIMIT_AUTH_REQUESTS", default=5, minimum=1)
RATE_LIMIT_MESSAGE_REQUESTS = int_from_env("RATE_LIMIT_MESSAGE_REQUESTS", default=30, minimum=1)
RATE_LIMIT_API_REQUESTS = int_from_env("RATE_LIMIT_API_REQUESTS", default=100, minimum=1)
