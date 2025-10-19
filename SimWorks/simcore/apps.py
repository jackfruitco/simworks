from django.apps import AppConfig


class SimcoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "simcore"

    # e.g. {"app", "App", "AppName"}
    # simcore_ai_django already adds all app names to this (normed)
    identity_strip_tokens = {}

    def ready(self):
        # Import all built-in tools
        import simcore.tools.builtins
