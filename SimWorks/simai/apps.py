# simai/apps.py

from django.apps import AppConfig

class SimManAIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "simai"

    def ready(self):
        import simai.signals