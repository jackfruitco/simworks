from django.apps import AppConfig

class ChatLabConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = "chatlab"

    def ready(self):
        import chatlab.signals