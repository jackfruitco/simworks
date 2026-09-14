"""Async/task execution settings (Django Tasks, channels, Celery, rate limits)."""

import os

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
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

if REDIS_PASSWORD:
    REDIS_BASE = f"redis://:{REDIS_PASSWORD}@{REDIS_HOSTNAME}:{REDIS_PORT}"
else:
    REDIS_BASE = f"redis://{REDIS_HOSTNAME}:{REDIS_PORT}"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [f"{REDIS_BASE}/0"],
        },
    }
}

# Redis database allocation (keep in sync with the docstring on
# apps.common.ratelimit.get_redis_client):
#   0 = channels layer        3 = API rate limiting
#   1 = Celery broker         4 = Django cache (below)
#   2 = Celery results
#
# Without a cache backend Django falls back to per-process locmem, which
# quietly degrades everything built on it: allauth's ACCOUNT_RATE_LIMITS
# become per-worker and reset on restart, Celery workers share no state with
# web workers, and the sim_debug toggles are invisible across processes.
#
# REDIS_HOSTNAME defaults to "redis" but can be set empty to run without
# Redis at all (see apps.common.ratelimit.get_redis_client), so fall back to
# locmem in that case rather than failing at startup.
if REDIS_HOSTNAME:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": f"{REDIS_BASE}/4",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
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
