from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class SimulationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "simulation"
    label = name

    # e.g. {"app", "App", "AppName"}
    # simcore_ai_django already adds all app names to this (normed)
    identity_strip_tokens = ["Patient"]

    def ready(self):
        # Import all built-in tools
        autodiscover_modules("tools.builtins")
