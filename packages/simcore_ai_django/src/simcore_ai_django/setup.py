from __future__ import annotations

from django.conf import settings
from simcore_ai.tracing import service_span_sync

from simcore_ai.client.registry import create_client_from_dict
from simcore_ai.types import AIClientConfig


def configure_ai_clients() -> None:
    """
    Initialize simcore_ai client registry from Django settings.AI_PROVIDERS.

    Example settings:
    AI_PROVIDERS = {
        "default": {
            "provider": "openai",
            "api_key": "sk-...",
            "model": "gpt-5-mini",
            # optional:
            # "base_url": None,
            # "timeout_s": 60,
            # "default": true,  # will be treated as default too
        },
        "openai-images": {
            "provider": "openai",
            "api_key": "sk-...",
            "model": "gpt-image-1",
        },
        "anthropic-core": {
            "provider": "anthropic",
            "api_key": "anth-...",
            "model": "claude-3-7-sonnet",
        },
    }
    """
    providers = getattr(settings, "AI_PROVIDERS", {}) or {}
    first = True

    with service_span_sync(
        "ai.clients.configure",
        attributes={"ai.providers.count": len(providers)},
    ):
        for name, cfg in providers.items():
            with service_span_sync(
                "ai.clients.configure.entry",
                attributes={"ai.client_name": name},
            ):
                if not isinstance(cfg, dict):
                    raise ValueError(f"AI_PROVIDERS['{name}'] must be a dict, got: {type(cfg)}")

                is_default = bool(cfg.get("default")) or (name == "default") or first

                # Merge global AI_CLIENT_DEFAULTS from settings (if any)
                client_defaults = getattr(settings, "AI_CLIENT_DEFAULTS", {}) or {}
                if not isinstance(client_defaults, dict):
                    raise ValueError("AI_CLIENT_DEFAULTS must be a dict if defined.")

                with service_span_sync("ai.clients.configure.defaults"):
                    client_cfg = AIClientConfig(**client_defaults)

                create_client_from_dict(
                    cfg_dict=cfg,
                    name=name,
                    make_default=is_default,
                    replace=True,
                    client_config=client_cfg,
                )
                first = False