# packages/simcore_ai_django/src/simcore_ai_django/checks.py
from __future__ import annotations

"""
Django system checks for SIMCORE AI configuration & registries.

This module hosts two groups of checks:

1) Settings shape validation for the consolidated `SIMCORE_AI` dict.
   - Ensures PROVIDERS/CLIENTS structures are mappings
   - Surfaces type issues and missing links
   - Gentle guidance on defaults & timeouts

2) Registry integrity checks (codecs/services/prompt sections/schemas).
   - Detects identity **collisions** (same `(namespace, kind, name)` bound to different classes)
     * Error when `SIMCORE_COLLISIONS_STRICT` is True (default)
     * Warning when strict is False (dev mode)
     * Check ID: `SIMCORE-ID-001`
   - Detects **invalid identities** (empty/illegal characters) if any slipped through
     * Error always (registries already try to prevent these)
     * Check ID: `SIMCORE-ID-002`

These checks run at startup and can be invoked with `python manage.py check`.
"""

from typing import Any, Dict, List, Optional, Iterable, Tuple
from collections.abc import Mapping
import logging
import re

from django.conf import settings
from django.core import checks

from simcore_ai.tracing import service_span_sync

# Django-layer registries
from simcore_ai_django.codecs.registry import codecs as codec_registry
from simcore_ai_django.services.registry import services as service_registry
from simcore_ai_django.promptkit.registry import prompt_sections as prompt_registry
from simcore_ai_django.schemas.registry import schemas as schema_registry

LOGGER = logging.getLogger(__name__)
TAG = "simcore_ai"
CHECK_ID_PREFIX = "SIMCORE-ID"

_ALLOWED_RE = re.compile(r"^[A-Za-z0-9._-]+$")


# ---------------------------------------------------------------------------
# Settings validation (retained, updated docstring from legacy module)
# ---------------------------------------------------------------------------

@checks.register(checks.Tags.compatibility, checks.Tags.security, checks.Tags.settings)
def check_simcore_ai_settings(app_configs: Optional[Iterable] = None, **kwargs) -> List[checks.CheckMessage]:
    """
    Validate SIMCORE_AI settings structure and key fields.

    Expected shape:

    SIMCORE_AI = {
        "PROVIDERS": {
            "<prov-key>": {
                "provider": "openai" | "anthropic" | "vertex" | "azure_openai" | "local",
                "label": str | None,
                "base_url": str | None,
                "api_key": str | None,
                "api_key_env": str | None,
                "model": str | None,
                "organization": str | None,
                "timeout_s": float | int | None,
            },
            ...
        },
        "CLIENTS": {
            "<client-name>": {
                "provider": "<prov-key>",
                "default": bool,
                "enabled": bool,
                # Overrides (optional)
                "model": str | None,
                "base_url": str | None,
                "api_key": str | None,
                "api_key_env": str | None,
                "timeout_s": float | int | None,
                # Runtime knobs (optional)
                "client_config": dict | None,
            },
            ...
        },
        "CLIENT_DEFAULTS": { ... },          # runtime knobs for AIClient
        "HEALTHCHECK_ON_START": True | False # optional, defaults True
    }
    """
    with service_span_sync("ai.clients.checks"):
        messages: List[checks.CheckMessage] = []

        sim: Mapping[str, Any] = getattr(settings, "SIMCORE_AI", {}) or {}
        if not isinstance(sim, Mapping):
            messages.append(
                checks.Error(
                    "SIMCORE_AI must be a dict-like mapping.",
                    hint="Example: SIMCORE_AI = {'PROVIDERS': {...}, 'CLIENTS': {...}}",
                    obj="settings.SIMCORE_AI",
                    id=f"{TAG}.E000",
                )
            )
            return messages

        # --- PROVIDERS --------------------------------------------------------
        providers: Mapping[str, Dict[str, Any]] = sim.get("PROVIDERS", {}) or {}
        if not isinstance(providers, Mapping):
            messages.append(
                checks.Error(
                    "SIMCORE_AI['PROVIDERS'] must be a dict-like mapping.",
                    hint="Example: SIMCORE_AI['PROVIDERS'] = {'openai': {'provider': 'openai', 'api_key_env': 'OPENAI_API_KEY'}}",
                    obj="settings.SIMCORE_AI['PROVIDERS']",
                    id=f"{TAG}.E001",
                )
            )
            return messages

        if not providers:
            messages.append(
                checks.Warning(
                    "SIMCORE_AI['PROVIDERS'] is empty — no AI clients can be constructed.",
                    hint="Define at least one provider entry.",
                    obj="settings.SIMCORE_AI['PROVIDERS']",
                    id=f"{TAG}.W001",
                )
            )

        for pkey, cfg in providers.items():
            with service_span_sync("ai.clients.checks.provider", attributes={"ai.provider_key": pkey}):
                if not isinstance(cfg, Mapping):
                    messages.append(
                        checks.Error(
                            f"SIMCORE_AI['PROVIDERS']['{pkey}'] must be a dict.",
                            hint="Each provider entry must be a mapping of fields like provider/model/api_key_env.",
                            obj=f"settings.SIMCORE_AI['PROVIDERS']['{pkey}']",
                            id=f"{TAG}.E002",
                        )
                    )
                    continue

                provider = cfg.get("provider")
                if not provider or not isinstance(provider, str):
                    messages.append(
                        checks.Error(
                            f"SIMCORE_AI['PROVIDERS']['{pkey}']['provider'] is required and must be a non-empty string.",
                            hint="Example: {'provider': 'openai', 'api_key_env': 'OPENAI_API_KEY'}",
                            obj=f"settings.SIMCORE_AI['PROVIDERS']['{pkey}']",
                            id=f"{TAG}.E003",
                        )
                    )

                api_key = cfg.get("api_key")
                api_key_env = cfg.get("api_key_env")
                if not api_key and not api_key_env:
                    messages.append(
                        checks.Warning(
                            f"SIMCORE_AI['PROVIDERS']['{pkey}'] has no 'api_key' or 'api_key_env'.",
                            hint="Set 'api_key_env' to the name of an environment variable holding your key.",
                            obj=f"settings.SIMCORE_AI['PROVIDERS']['{pkey}']",
                            id=f"{TAG}.W002",
                        )
                    )

                base_url = cfg.get("base_url", None)
                timeout_s = cfg.get("timeout_s", None)
                if base_url is not None and not isinstance(base_url, str):
                    messages.append(
                        checks.Warning(
                            f"SIMCORE_AI['PROVIDERS']['{pkey}']['base_url'] should be a string or None.",
                            obj=f"settings.SIMCORE_AI['PROVIDERS']['{pkey}']",
                            id=f"{TAG}.W003",
                        )
                    )
                if timeout_s is not None:
                    try:
                        float(timeout_s)
                    except Exception:
                        messages.append(
                            checks.Warning(
                                f"SIMCORE_AI['PROVIDERS']['{pkey}']['timeout_s'] should be numeric (seconds).",
                                obj=f"settings.SIMCORE_AI['PROVIDERS']['{pkey}']",
                                id=f"{TAG}.W004",
                            )
                        )

        # --- CLIENTS ----------------------------------------------------------
        clients: Mapping[str, Dict[str, Any]] = sim.get("CLIENTS", {}) or {}
        if not isinstance(clients, Mapping):
            messages.append(
                checks.Error(
                    "SIMCORE_AI['CLIENTS'] must be a dict-like mapping.",
                    hint="Example: SIMCORE_AI['CLIENTS'] = {'openai:prod-gpt-4o-mini': {'provider': 'openai', 'default': True}}",
                    obj="settings.SIMCORE_AI['CLIENTS']",
                    id=f"{TAG}.E005",
                )
            )
            return messages

        if not clients:
            messages.append(
                checks.Warning(
                    "SIMCORE_AI['CLIENTS'] is empty — no AI clients will be registered.",
                    hint="Define at least one client referencing a provider.",
                    obj="settings.SIMCORE_AI['CLIENTS']",
                    id=f"{TAG}.W005",
                )
            )

        default_clients: list[str] = []
        for cname, cfg in clients.items():
            with service_span_sync("ai.clients.checks.client", attributes={"ai.client_name": cname}):
                if not isinstance(cfg, Mapping):
                    messages.append(
                        checks.Error(
                            f"SIMCORE_AI['CLIENTS']['{cname}'] must be a dict.",
                            hint="Each client entry must be a mapping with at least a 'provider' key.",
                            obj=f"settings.SIMCORE_AI['CLIENTS']['{cname}']",
                            id=f"{TAG}.E006",
                        )
                    )
                    continue

                prov_key = cfg.get("provider")
                if not prov_key or not isinstance(prov_key, str):
                    messages.append(
                        checks.Error(
                            f"SIMCORE_AI['CLIENTS']['{cname}']['provider'] is required and must be a non-empty string.",
                            hint="Set it to one of the keys from SIMCORE_AI['PROVIDERS'].",
                            obj=f"settings.SIMCORE_AI['CLIENTS']['{cname}']",
                            id=f"{TAG}.E007",
                        )
                    )
                elif prov_key not in providers:
                    messages.append(
                        checks.Error(
                            f"SIMCORE_AI['CLIENTS']['{cname}']['provider'] references unknown provider key '{prov_key}'.",
                            hint=f"Choose one of: {sorted(providers.keys())}",
                            obj=f"settings.SIMCORE_AI['CLIENTS']['{cname}']",
                            id=f"{TAG}.E008",
                        )
                    )

                for key in ("model", "base_url", "api_key", "api_key_env"):
                    if key in cfg and cfg[key] is not None and not isinstance(cfg[key], str):
                        messages.append(
                            checks.Warning(
                                f"SIMCORE_AI['CLIENTS']['{cname}']['{key}'] should be a string.",
                                obj=f"settings.SIMCORE_AI['CLIENTS']['{cname}']",
                                id=f"{TAG}.W006",
                            )
                        )
                if "timeout_s" in cfg and cfg["timeout_s"] is not None:
                    try:
                        float(cfg["timeout_s"])
                    except Exception:
                        messages.append(
                            checks.Warning(
                                f"SIMCORE_AI['CLIENTS']['{cname}']['timeout_s'] should be numeric (seconds).",
                                obj=f"settings.SIMCORE_AI['CLIENTS']['{cname}']",
                                id=f"{TAG}.W007",
                            )
                        )

                if _is_truthy(cfg.get("default", False)):
                    default_clients.append(cname)

        if clients and not default_clients:
            messages.append(
                checks.Warning(
                    "No default AI client configured.",
                    hint=(
                        "Set 'default': True on one client. If omitted, startup will warn and "
                        "select the first enabled client as the default."
                    ),
                    obj="settings.SIMCORE_AI['CLIENTS']",
                    id=f"{TAG}.W008",
                )
            )
        if len(default_clients) > 1:
            messages.append(
                checks.Warning(
                    f"Multiple clients are marked as default: {default_clients!r}",
                    hint="Startup will keep the first marked default and ignore the rest.",
                    obj="settings.SIMCORE_AI['CLIENTS']",
                    id=f"{TAG}.W009",
                )
            )

        client_defaults = sim.get("CLIENT_DEFAULTS", {}) or {}
        if client_defaults and not isinstance(client_defaults, Mapping):
            messages.append(
                checks.Error(
                    "SIMCORE_AI['CLIENT_DEFAULTS'] must be a dict if defined.",
                    hint="Example: SIMCORE_AI['CLIENT_DEFAULTS'] = {'max_retries': 3, 'timeout_s': 45}",
                    obj="settings.SIMCORE_AI['CLIENT_DEFAULTS']",
                    id=f"{TAG}.E010",
                )
            )
        elif isinstance(client_defaults, Mapping):
            known_keys = {"max_retries", "timeout_s", "telemetry_enabled", "log_prompts", "raise_on_error"}
            for key, val in client_defaults.items():
                if key not in known_keys:
                    messages.append(
                        checks.Warning(
                            f"Unknown SIMCORE_AI['CLIENT_DEFAULTS'] key: '{key}'",
                            hint=f"Known keys: {sorted(known_keys)}",
                            obj="settings.SIMCORE_AI['CLIENT_DEFAULTS']",
                            id=f"{TAG}.W010",
                        )
                    )
                if key in {"max_retries"} and not isinstance(val, int):
                    messages.append(
                        checks.Warning(
                            f"SIMCORE_AI['CLIENT_DEFAULTS']['{key}'] should be an int.",
                            obj="settings.SIMCORE_AI['CLIENT_DEFAULTS']",
                            id=f"{TAG}.W011",
                        )
                    )
                if key in {"timeout_s"} and not isinstance(val, (int, float)):
                    messages.append(
                        checks.Warning(
                            f"SIMCORE_AI['CLIENT_DEFAULTS']['{key}'] should be numeric (seconds).",
                            obj="settings.SIMCORE_AI['CLIENT_DEFAULTS']",
                            id=f"{TAG}.W012",
                        )
                    )
                if key in {"telemetry_enabled", "log_prompts", "raise_on_error"} and not isinstance(val, bool):
                    messages.append(
                        checks.Warning(
                            f"SIMCORE_AI['CLIENT_DEFAULTS']['{key}'] should be a boolean.",
                            obj="settings.SIMCORE_AI['CLIENT_DEFAULTS']",
                            id=f"{TAG}.W013",
                        )
                    )

        if "HEALTHCHECK_ON_START" in sim:
            val = sim.get("HEALTHCHECK_ON_START")
            if not isinstance(val, bool):
                messages.append(
                    checks.Warning(
                        "SIMCORE_AI['HEALTHCHECK_ON_START'] should be a boolean.",
                        obj="settings.SIMCORE_AI['HEALTHCHECK_ON_START']",
                        id=f"{TAG}.W014",
                    )
                )

        return messages


def _is_truthy(val: Any) -> bool:
    """Best-effort truthiness coercion for settings-like values."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


# ---------------------------------------------------------------------------
# Registry integrity checks
# ---------------------------------------------------------------------------

@checks.register(checks.Tags.models)
def check_simcore_ai_registries(app_configs: Optional[Iterable] = None, **kwargs) -> List[checks.CheckMessage]:
    """Validate identity collisions and illegal identities across registries.

    - Collisions → `SIMCORE-ID-001` (Error if strict, Warning if non-strict)
    - Invalid identities → `SIMCORE-ID-002` (Error)
    """
    with service_span_sync("ai.registries.checks"):
        messages: List[checks.CheckMessage] = []
        strict = bool(getattr(settings, "SIMCORE_COLLISIONS_STRICT", True))

        registries = [
            ("codec", codec_registry),
            ("service", service_registry),
            ("prompt_section", prompt_registry),
            ("schema", schema_registry),
        ]

        # Collisions (SIMCORE-ID-001)
        for kind, reg in registries:
            try:
                collisions = list(reg.collisions())
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.exception("registry.collisions.failed %s", kind)
                continue
            if not collisions:
                continue
            joined = ", ".join([".".join(t) for t in collisions])
            if strict:
                messages.append(
                    checks.Error(
                        f"{kind} registry has identity collisions: {joined}",
                        hint=(
                            "Collisions occur when different classes share the same (namespace, kind, name). "
                            "Rename one class via its decorator or adjust your derivation tokens."
                        ),
                        obj=f"simcore_ai_django.{kind}.registry",
                        id=f"{CHECK_ID_PREFIX}-001",
                    )
                )
            else:
                messages.append(
                    checks.Warning(
                        f"{kind} registry has identity collisions (non-strict mode): {joined}",
                        hint=(
                            "Enable SIMCORE_COLLISIONS_STRICT=True to fail hard, or resolve by renaming."
                        ),
                        obj=f"simcore_ai_django.{kind}.registry",
                        id=f"{CHECK_ID_PREFIX}-001",
                    )
                )

        # Invalid identities (SIMCORE-ID-002) — should not happen because registries validate,
        # but we defensively re-check the stored keys and surface errors if any slipped through.
        def _validate_tuple3(t: Tuple[str, str, str]) -> Optional[str]:
            ns, kd, nm = t
            for label, val in (("namespace", ns), ("kind", kd), ("name", nm)):
                if not isinstance(val, str) or not val.strip():
                    return f"{label} is empty or not a string: {val!r}"
                if not _ALLOWED_RE.match(val):
                    return f"{label} contains illegal characters: {val!r}"
            return None

        for kind, reg in registries:
            try:
                registered = list(reg.list())
            except Exception as exc:  # pragma: no cover - defensive
                LOGGER.exception("registry.list.failed %s", kind)
                continue
            for item in registered:
                problem = _validate_tuple3(item.identity)
                if problem:
                    messages.append(
                        checks.Error(
                            f"Invalid identity in {kind} registry: {'.'.join(item.identity)} ({problem})",
                            hint="This should have been prevented at registration time; check your decorator derivation.",
                            obj=f"simcore_ai_django.{kind}.registry",
                            id=f"{CHECK_ID_PREFIX}-002",
                        )
                    )

        return messages
