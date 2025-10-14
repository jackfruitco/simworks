# simcore_ai_django/checks.py
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from django.conf import settings
from django.core import checks

from simcore_ai.tracing import service_span_sync


TAG = "simcore_ai"


def _is_truthy(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(val)


@checks.register(checks.Tags.compatibility, checks.Tags.security, checks.Tags.settings)
def check_ai_providers(app_configs: Optional[Iterable] = None, **kwargs) -> List[checks.CheckMessage]:
    with service_span_sync("ai.clients.checks"):
        messages: List[checks.CheckMessage] = []

        # --- Presence / type checks -------------------------------------------------
        providers: Mapping[str, Dict[str, Any]] = getattr(settings, "AI_PROVIDERS", {}) or {}

        if not isinstance(providers, Mapping):
            messages.append(
                checks.Error(
                    "AI_PROVIDERS must be a dict-like mapping.",
                    hint="Example: AI_PROVIDERS = {'default': {'provider': 'openai', 'api_key': '...'}}",
                    obj="settings.AI_PROVIDERS",
                    id=f"{TAG}.E001",
                )
            )
            return messages  # cannot proceed

        if not providers:
            messages.append(
                checks.Warning(
                    "AI_PROVIDERS is empty — no AI clients will be registered.",
                    hint="Define at least one entry, e.g. a 'default' client.",
                    obj="settings.AI_PROVIDERS",
                    id=f"{TAG}.W001",
                )
            )
            # We can still proceed to check AI_CLIENT_DEFAULTS below.

        # --- Validate each provider entry ------------------------------------------
        allow_missing_keys = _is_truthy(getattr(settings, "AI_ALLOW_MISSING_KEYS", False))
        is_debug = _is_truthy(getattr(settings, "DEBUG", False))

        seen_defaults = set()

        for name, cfg in providers.items():
            with service_span_sync("ai.clients.checks.entry", attributes={"ai.client_name": name}):
                if not isinstance(cfg, Mapping):
                    messages.append(
                        checks.Error(
                            f"AI_PROVIDERS['{name}'] must be a dict.",
                            hint="Each provider entry must be a mapping of fields like provider/api_key/model.",
                            obj=f"settings.AI_PROVIDERS['{name}']",
                            id=f"{TAG}.E002",
                        )
                    )
                    continue

                provider = cfg.get("provider")
                api_key = cfg.get("api_key")
                model = cfg.get("model", None)

                # provider required
                if not provider or not isinstance(provider, str):
                    messages.append(
                        checks.Error(
                            f"AI_PROVIDERS['{name}']['provider'] is required and must be a non-empty string.",
                            hint="Example: {'provider': 'openai', 'api_key': 'sk-...'}",
                            obj=f"settings.AI_PROVIDERS['{name}']",
                            id=f"{TAG}.E003",
                        )
                    )

                # api_key required unless explicitly allowed or in DEBUG w/ override
                if not api_key:
                    if allow_missing_keys or is_debug:
                        messages.append(
                            checks.Warning(
                                f"AI_PROVIDERS['{name}']['api_key'] is missing.",
                                hint="Set AI_ALLOW_MISSING_KEYS=True for local dev or provide a real key via env.",
                                obj=f"settings.AI_PROVIDERS['{name}']",
                                id=f"{TAG}.W002",
                            )
                        )
                    else:
                        messages.append(
                            checks.Error(
                                f"AI_PROVIDERS['{name}']['api_key'] is required.",
                                hint="Provide an API key via env or allow missing keys only in development.",
                                obj=f"settings.AI_PROVIDERS['{name}']",
                                id=f"{TAG}.E004",
                            )
                        )

                # Optional: type checks for common fields
                base_url = cfg.get("base_url", None)
                timeout_s = cfg.get("timeout_s", None)
                if base_url is not None and not isinstance(base_url, str):
                    messages.append(
                        checks.Warning(
                            f"AI_PROVIDERS['{name}']['base_url'] should be a string or None.",
                            obj=f"settings.AI_PROVIDERS['{name}']",
                            id=f"{TAG}.W003",
                        )
                    )
                if timeout_s is not None:
                    try:
                        float(timeout_s)
                    except Exception:
                        messages.append(
                            checks.Warning(
                                f"AI_PROVIDERS['{name}']['timeout_s'] should be numeric (seconds).",
                                obj=f"settings.AI_PROVIDERS['{name}']",
                                id=f"{TAG}.W004",
                            )
                        )

                # Track candidates for default
                if name == "default" or _is_truthy(cfg.get("default", False)):
                    seen_defaults.add(name)

        # --- Default client guidance -----------------------------------------------
        if providers and not seen_defaults:
            messages.append(
                checks.Warning(
                    "No default AI client configured.",
                    hint=(
                        "Mark one entry as default by naming it 'default' or setting "
                        "'default': True on a provider config. "
                        "get_ai_client() without args will fail otherwise."
                    ),
                    obj="settings.AI_PROVIDERS",
                    id=f"{TAG}.W005",
                )
            )

        # --- AI_CLIENT_DEFAULTS sanity checks --------------------------------------
        client_defaults = getattr(settings, "AI_CLIENT_DEFAULTS", {}) or {}
        if client_defaults and not isinstance(client_defaults, Mapping):
            messages.append(
                checks.Error(
                    "AI_CLIENT_DEFAULTS must be a dict if defined.",
                    hint="Example: AI_CLIENT_DEFAULTS = {'max_retries': 3, 'timeout_s': 45}",
                    obj="settings.AI_CLIENT_DEFAULTS",
                    id=f"{TAG}.E005",
                )
            )
        else:
            # Optional lightweight validation of a few known keys
            known_keys = {"max_retries", "timeout_s", "telemetry_enabled", "log_prompts", "raise_on_error"}
            for key, val in client_defaults.items():
                if key not in known_keys:
                    messages.append(
                        checks.Warning(
                            f"Unknown AI_CLIENT_DEFAULTS key: '{key}'",
                            hint=f"Known keys: {sorted(known_keys)}",
                            obj="settings.AI_CLIENT_DEFAULTS",
                            id=f"{TAG}.W006",
                        )
                    )
                if key in {"max_retries"} and not isinstance(val, int):
                    messages.append(
                        checks.Warning(
                            f"AI_CLIENT_DEFAULTS['{key}'] should be an int.",
                            obj="settings.AI_CLIENT_DEFAULTS",
                            id=f"{TAG}.W007",
                        )
                    )
                if key in {"timeout_s"} and not isinstance(val, (int, float)):
                    messages.append(
                        checks.Warning(
                            f"AI_CLIENT_DEFAULTS['{key}'] should be numeric (seconds).",
                            obj="settings.AI_CLIENT_DEFAULTS",
                            id=f"{TAG}.W008",
                        )
                    )
                if key in {"telemetry_enabled", "log_prompts", "raise_on_error"} and not isinstance(val, bool):
                    messages.append(
                        checks.Warning(
                            f"AI_CLIENT_DEFAULTS['{key}'] should be a boolean.",
                            obj="settings.AI_CLIENT_DEFAULTS",
                            id=f"{TAG}.W009",
                        )
                    )

        return messages