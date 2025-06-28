from django.apps import AppConfig


class SimcoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "simcore"

    def ready(self):
        # Import all built-in tools
        import simcore.tools.builtins
