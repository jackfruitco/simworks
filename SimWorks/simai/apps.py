# simai/apps.py
import warnings

from django.apps import AppConfig


class SimManAIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "simai"

    def ready(self):
        warnings.warn("Module is deprecated. Use `simcore.ai` instead.", DeprecationWarning, stacklevel=2)
        import simai.signals
        import simai.prompts.builtins
