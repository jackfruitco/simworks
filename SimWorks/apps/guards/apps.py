from django.apps import AppConfig


class GuardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.guards"
    verbose_name = "Usage Guards"

    def ready(self):
        from .signals import _connect_signals

        _connect_signals()
