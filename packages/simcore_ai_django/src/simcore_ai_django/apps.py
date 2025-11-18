# simcore_ai_django/apps.py


import os

"""
simcore_ai_django.apps
======================

AppConfig for the `simcore_ai_django` integration.

Responsibilities
----------------
- Bootstrap AI providers/clients from `settings.SIMCORE_AI` during Django startup.
- Autodiscover optional integration modules (`ai.receivers`, `ai.task_backends`, `ai.prompts`,
  `ai.services`, `ai.codecs`) across installed apps.
- Emit tracing spans for observability.

Notes
-----
- The actual client/provider configuration and idempotency logic lives in
  `simcore_ai_django.setup.configure_ai_clients()`, which is safe to call multiple times.
"""

from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules
from simcore_ai.tracing import service_span_sync

import logging

logger = logging.getLogger(__name__)


class SimcoreAIDjangoConfig(AppConfig):
    """Django AppConfig for simcore_ai_django."""

    name = "simcore_ai_django"

    def ready(self) -> None:
        """
        Initialize AI clients and autodiscover integration modules.

        This method is invoked by Django during app registry finalization. It delegates
        to `configure_ai_clients()` for provider/client setup (idempotent), then runs
        autodiscovery hooks to allow project apps to register receivers, prompts, etc.
        """
        if os.environ.get("DJANGO_SKIP_READY") == "1":
            return

        from .setup import configure_ai_clients, autodiscover_all

        with service_span_sync("simcore.django_app.ready"):
            with service_span_sync("simcore.clients.setup"):
                configure_ai_clients()

            with service_span_sync("simcore.autodiscover"):
                autodiscover_all()
                logger.info("all ")



