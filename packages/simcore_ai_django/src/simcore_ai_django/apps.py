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
            with service_span_sync("ai.autodiscover.task_backends"):    # Add new backends here
                autodiscover_modules("ai.task_backends")
            with service_span_sync("ai.autodiscover.prompts"):          # Add new prompts here
                autodiscover_modules("ai.prompts")
            with service_span_sync("ai.autodiscover.services"):         # Add new services here
                autodiscover_modules("ai.services")
            with service_span_sync("ai.autodiscover.codecs"):           # Add new codecs here
                autodiscover_modules("ai.codecs")
