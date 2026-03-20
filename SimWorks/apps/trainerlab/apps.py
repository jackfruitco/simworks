# SimWorks/apps/trainerlab/apps.py
from django.apps import AppConfig


class TrainerlabConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.trainerlab"

    def ready(self) -> None:
        from . import signals  # noqa: F401
