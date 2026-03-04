from typing import ClassVar

from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class SimCoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.simcore"

    # e.g. {"app", "App", "AppName"}
    # orchestrai_django already adds all app names to this (normed)
    identity_strip_tokens: ClassVar[tuple[str, ...]] = ("Patient",)

    def ready(self):
        # Import all built-in tools
        autodiscover_modules("tools.builtins")
