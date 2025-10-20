from __future__ import annotations

import importlib
from types import ModuleType

from django.apps import apps


def gather_app_identity_tokens() -> tuple[str, ...]:
    tokens: list[str] = []
    # scan installed apps for optional ai.identity contributors
    for appcfg in apps.get_app_configs():
        mod_name = f"{appcfg.name}.ai.identity"
        try:
            mod: ModuleType = importlib.import_module(mod_name)  # type: ignore[assignment]
        except Exception:
            continue
        # common names we support in contributor modules
        for attr in ("APP_IDENTITY_STRIP_TOKENS", "IDENTITY_STRIP_TOKENS", "STRIP_TOKENS"):
            try:
                val = getattr(mod, attr, None)
                if val:
                    for t in val:
                        if isinstance(t, str):
                            tokens.append(t)
            except Exception:
                continue
        # callable provider
        try:
            provider = getattr(mod, "get_identity_strip_tokens", None)
            if callable(provider):
                for t in provider() or ():
                    if isinstance(t, str):
                        tokens.append(t)
        except Exception:
            continue
    # de-dup case-insensitively while preserving order
    seen = set()
    dedup: list[str] = []
    for t in tokens:
        k = t.casefold()
        if k and k not in seen:
            seen.add(k)
            dedup.append(t)
    return tuple(dedup)
