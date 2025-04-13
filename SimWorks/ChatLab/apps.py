from django.apps import AppConfig

class ChatLabConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = "ChatLab"

    def ready(self):
        import ChatLab.signals