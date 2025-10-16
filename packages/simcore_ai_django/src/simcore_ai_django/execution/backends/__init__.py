# simcore_ai_django/execution/backends/__init__.py
from .immediate import ImmediateBackend
from .celery_backend import CeleryBackend
# from .django_tasks_backend import DjangoTasksBackend  # keep commented until implemented

__all__ = [
    "ImmediateBackend",
    "CeleryBackend",
    # "DjangoTasksBackend", # TODO: Add DjangoTasksBackend when upgrading to Django 6.0
]