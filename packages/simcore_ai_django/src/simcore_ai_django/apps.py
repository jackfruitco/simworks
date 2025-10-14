from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules
from simcore_ai.tracing import service_span_sync

class SimcoreAIDjangoConfig(AppConfig):
    name = "simcore_ai_django"

    def ready(self):
        from .setup import configure_ai_clients
        with service_span_sync("ai.django_app.ready"):
            with service_span_sync("ai.clients.setup"):
                configure_ai_clients()

            # Discover per-app receivers and prompts
            with service_span_sync("ai.autodiscover.receivers"):
                autodiscover_modules("ai.receivers")
            with service_span_sync("ai.autodiscover.prompts"):
                autodiscover_modules("ai.prompts")
            with service_span_sync("ai.autodiscover.services"):
                autodiscover_modules("ai.services")
            with service_span_sync("ai.autodiscover.codecs"):
                autodiscover_modules("ai.codecs")
