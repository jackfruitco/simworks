from django.apps import AppConfig


class ChatLabConfig(AppConfig):
    name = "chatlab"
    label = name

    # orchestrai_django already adds all app names to this (normed)
    AI_IDENTITY_STRIP_TOKENS = ("Patient","Chatlab","chatlab")

    def ready(self):
        from simulation.history_registry import register_history_provider
        from .models import Message

        def chatlab_history(simulation):
            return [
                {
                    "source": msg._meta.app_label,
                    "timestamp": msg.timestamp,
                    "role": msg.role,
                    "sender": msg.display_name or str(msg.sender),
                    "content": msg.content,
                }
                for msg in Message.objects.filter(simulation=simulation).order_by(
                    "timestamp"
                )
            ]

        register_history_provider("chatlab", chatlab_history)
