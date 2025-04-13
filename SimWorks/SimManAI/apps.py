# SimManAI/apps.py

from django.apps import AppConfig

class SimManAIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "SimManAI"

    def ready(self):
        import SimManAI.signals