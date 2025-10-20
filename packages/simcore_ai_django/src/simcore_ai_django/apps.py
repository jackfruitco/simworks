from __future__ import annotations

import os

from simcore_ai_django.decorators.helpers import gather_app_identity_tokens

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

        from . import identity as _identity_mod
        with service_span_sync("ai.identity.collect_tokens"):
            try:
                _identity_mod.APP_IDENTITY_STRIP_TOKENS = gather_app_identity_tokens()
            except Exception:
                # always keep startup resilient
                logger.debug("Failed collecting APP_IDENTITY_STRIP_TOKENS", exc_info=True)

        from .setup import configure_ai_clients

        with service_span_sync("ai.django_app.ready"):
            with service_span_sync("ai.clients.setup"):
                configure_ai_clients()

            with service_span_sync("ai.autodiscover.identity"):
                autodiscover_modules("ai.identity")
            # Discover per-app receivers and prompts
            with service_span_sync("ai.autodiscover.receivers"):
                autodiscover_modules("ai.receivers")
            with service_span_sync("ai.autodiscover.task_backends"):  # Add new backends here
                autodiscover_modules("ai.task_backends")
            with service_span_sync("ai.autodiscover.prompts"):  # Add new prompts here
                autodiscover_modules("ai.prompts")
            with service_span_sync("ai.autodiscover.services"):  # Add new services here
                autodiscover_modules("ai.services")
            with service_span_sync("ai.autodiscover.codecs"):  # Add new codecs here
                autodiscover_modules("ai.codecs")
