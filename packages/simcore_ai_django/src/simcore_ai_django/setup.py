# simcore_ai_django/setup.py
"""
simcore_ai_django.setup
=======================

Django-side bootstrap for AI providers and clients.

Responsibilities
----------------
- Read and validate `settings.SIMCORE_AI`:
    SIMCORE_AI = {
        "PROVIDERS": { "<prov-key>": {provider, label?, base_url?, api_key?, api_key_env?,
                                      model?, organization?, timeout_s?}, ... },
        "CLIENTS":   { "<client-name>": {provider: "<prov-key>", default?, enabled?,
                                          model?, base_url?, api_key?, api_key_env?,
                                          timeout_s?, client_config?}, ... },
        "CLIENT_DEFAULTS": {...runtime knobs for AIClient...},
        "HEALTHCHECK_ON_START": True,
    }
- Build provider wiring (`AIProviderConfig`) and client registrations (`AIClientRegistration`).
- Merge client overrides into provider configs (without side effects) to produce effective configs.
- Create and register clients; select a default per policy:
    * If multiple `default=True`: log WARNINGs, keep the first one encountered.
    * If none: log WARNING and use the first enabled client as default.
- Optionally run a quick, non-fatal healthcheck against all registered clients.
- Be idempotent across multiple `apps.ready()` invocations (e.g., with autoreload).

Notes
-----
- No backwards compatibility with the old `AI_PROVIDERS`/`AI_CLIENT_DEFAULTS`.
- API key resolution order is handled inside the factory/merge workflow:
    client.api_key -> provider.api_key -> os.environ[client.api_key_env or provider.api_key_env]
"""

import logging
import os
from typing import Dict, Tuple

from django.conf import settings
from django.utils.module_loading import autodiscover_modules

from simcore_ai.client.registry import (
    create_client,
    set_default_client,
    is_configured as registry_is_configured,
)
from simcore_ai.client.schemas import AIProviderConfig, AIClientRegistration, AIClientConfig
from simcore_ai.client.utils import effective_provider_config
from simcore_ai.components import BaseComponent
from simcore_ai.registry import BaseRegistry
from simcore_ai.tracing import service_span_sync
from .health import healthcheck_all_registered

logger = logging.getLogger(__name__)

# Module-level idempotency guard. We still double-check the registry itself.
_CONFIGURED_SIGNATURE: Tuple[int, int] | None = None  # (num_providers, num_clients)


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable with sensible defaults."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def configure_ai_clients() -> None:
    """
    Initialize the simcore_ai client registry from Django settings.SIMCORE_AI.

    This function is safe to call multiple times during Django startup; it will
    short-circuit if the registry appears configured and the settings signature
    has not changed.
    """
    sim = getattr(settings, "SIMCORE_AI", None) or {}
    providers_cfg = sim.get("PROVIDERS", {}) or {}
    clients_cfg = sim.get("CLIENTS", {}) or {}
    client_defaults = sim.get("CLIENT_DEFAULTS", {}) or {}
    health_on_start = bool(sim.get("HEALTHCHECK_ON_START", True))
    # Env override wins:
    health_on_start = _env_bool("SIMCORE_AI_HEALTHCHECK_ON_START", health_on_start)

    # Idempotency: quick signature check (counts only, sufficient for autoreload loops)
    global _CONFIGURED_SIGNATURE
    current_sig = (len(providers_cfg), len(clients_cfg))
    if _CONFIGURED_SIGNATURE == current_sig and registry_is_configured():
        logger.info("AI clients already configured (skipping); providers=%d clients=%d",
                    current_sig[0], current_sig[1])
        return

    with service_span_sync(
        "simcore.clients.configure",
        attributes={
            "simcore.providers.count": len(providers_cfg),
            "simcore.clients.count": len(clients_cfg),
            "simcore.healthcheck_on_start": bool(health_on_start),
        },
    ):
        # --- Validate and build provider objects ---------------------------------
        providers: Dict[str, AIProviderConfig] = {}
        for pkey, payload in providers_cfg.items():
            if not isinstance(payload, dict):
                raise ValueError(f"SIMCORE_AI['PROVIDERS']['{pkey}'] must be a dict, got: {type(payload)}")
            prov = AIProviderConfig(**payload)
            providers[pkey] = prov

        # --- Validate and build client registrations ------------------------------
        registrations: list[AIClientRegistration] = []
        for cname, payload in clients_cfg.items():
            if not isinstance(payload, dict):
                raise ValueError(f"SIMCORE_AI['CLIENTS']['{cname}'] must be a dict, got: {type(payload)}")
            reg = AIClientRegistration(name=cname, **payload)
            registrations.append(reg)

        # --- Build AIClientConfig defaults ---------------------------------------
        if not isinstance(client_defaults, dict):
            raise ValueError("SIMCORE_AI['CLIENT_DEFAULTS'] must be a dict if defined.")
        client_cfg_defaults = AIClientConfig(**client_defaults)

        # --- Create clients & choose default per policy ---------------------------
        seen_default_name: str | None = None
        first_enabled_name: str | None = None

        for reg in registrations:
            if not reg.enabled:
                logger.info("AI client disabled; skipping: %s", reg.name)
                continue

            prov = providers.get(reg.provider)
            if prov is None:
                raise KeyError(f"Client '{reg.name}' references unknown provider key '{reg.provider}'")

            eff = effective_provider_config(prov, reg)
            client = create_client(
                eff,
                name=reg.name,
                make_default=False,   # select default after loop per policy
                replace=True,         # idempotent across reloads
                client_config=client_cfg_defaults,
            )

            # Persist healthcheck preference for orchestrator
            try:
                setattr(client, "healthcheck_enabled", bool(getattr(reg, "healthcheck", True)))
            except Exception:
                # Never let this crash startup
                pass

            if first_enabled_name is None:
                first_enabled_name = reg.name

            if reg.default:
                if seen_default_name is None:
                    seen_default_name = reg.name
                else:
                    logger.warning(
                        "Multiple default clients marked: already '%s', ignoring additional '%s'",
                        seen_default_name, reg.name
                    )

        # Select default per policy
        if seen_default_name:
            set_default_client(seen_default_name)
            logger.info("AI default client set to '%s' (first default=True)", seen_default_name)
        elif first_enabled_name:
            set_default_client(first_enabled_name)
            logger.warning("No default client marked; using first enabled '%s'", first_enabled_name)
        else:
            logger.warning("No enabled AI clients were configured.")

        # --- Optional healthcheck -------------------------------------------------
        if health_on_start:
            with service_span_sync("simcore.clients.healthcheck"):
                health_results = healthcheck_all_registered()
                # Summarize counts
                ok = sum(1 for _, (ok, _) in health_results.items() if ok)
                total = len(health_results)
                logger.info("AI healthcheck summary: %d/%d OK", ok, total)

        # Mark configured for idempotency
        _CONFIGURED_SIGNATURE = current_sig


def autodiscover_all() -> None:
    """
    Idempotent autodiscovery of AI integration modules across INSTALLED_APPS.

    Mirrors the calls in `SimcoreAIDjangoConfig.ready()` so that non-Django
    entrypoints (e.g., Celery workers/beat or management commands) can opt in
    to the same registration flow.
    """
    from .components import PromptSection, DjangoBaseService, DjangoBaseCodec

    def _tally_component(
        c: type[BaseComponent],
        r: BaseRegistry | None = None,
    ) -> tuple[int, tuple[str, ...]]:
        """Tally number of discovered components for a given component base."""
        if r is None:
            try:
                r = c.get_registry()
            except Exception:
                # Non-fatal: log at debug so failures are visible in traces without crashing startup.
                logger.debug("get_registry() failed for %s", c, exc_info=True)
                r = None

        if r is None:
            logger.info("No registry found for %s, ignoring", c)
            return 0, ()

        labels = r.all(as_str=True)
        return r.count(), labels

    with service_span_sync("simcore.autodiscover.identity"):
        autodiscover_modules("simcore.identity")
        autodiscover_modules("ai.identity")

    with service_span_sync("simcore.autodiscover.receivers"):
        autodiscover_modules("simcore.receivers")
        autodiscover_modules("ai.receivers")

    with service_span_sync("simcore.autodiscover.prompts"):
        autodiscover_modules("simcore.prompts")
        autodiscover_modules("ai.prompts")
        p_count, p_labels = _tally_component(PromptSection)
        logger.info(
            "Discovered %d PromptSections",
            p_count,
            extra={
                "prompt_sections.count": p_count,
                "prompt_sections.labels": p_labels,
            },
        )

    with service_span_sync("simcore.autodiscover.services"):
        autodiscover_modules("simcore.services")
        autodiscover_modules("ai.services")
        s_count, s_labels = _tally_component(DjangoBaseService)
        logger.info(
            "Discovered %d services",
            s_count,
            extra={
                "services.count": s_count,
                "services.labels": s_labels,
            },
        )

    with service_span_sync("simcore.autodiscover.codecs"):
        autodiscover_modules("simcore.codecs")
        autodiscover_modules("ai.codecs")
        c_count, c_labels = _tally_component(DjangoBaseCodec)
        logger.info(
            "Discovered %d codecs",
            c_count,
            extra={
                "codecs.count": c_count,
                "codecs.labels": c_labels,
            },
        )
