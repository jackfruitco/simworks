# orchestrai_django/integration.py

from __future__ import annotations

from typing import Any, Mapping

from orchestrai.conf.settings import Settings


def _coerce_mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    raise TypeError("Django settings for OrchestrAI must be a mapping or None")


def configure_from_django_settings(
    app: Any | None = None,
    *,
    namespace: str = "ORCA_CONFIG",
    legacy_namespace: str = "ORCA",
) -> Settings:
    """Load OrchestrAI configuration from ``django.conf.settings``.

    Preference order:
    1. A mapping stored under ``ORCA_CONFIG`` (default).
    2. Namespaced uppercase keys using ``legacy_namespace`` (e.g. ``ORCA_CLIENTS``).
    """

    from django.conf import settings as dj_settings  # type: ignore[attr-defined]

    conf = Settings()

    # Preferred path: explicit config mapping
    mapping = _coerce_mapping(getattr(dj_settings, namespace, None))
    if mapping or getattr(dj_settings, namespace, None) is not None:
        conf.update_from_mapping(mapping)
    else:
        conf.update_from_mapping(vars(dj_settings), namespace=legacy_namespace)

    if app is not None and hasattr(app, "configure"):
        app.configure(conf.as_dict())
    return conf


def django_autodiscover(app: Any, *, module_names: list[str] | None = None) -> None:
    """Django-native autodiscovery. Imports module_names across INSTALLED_APPS."""

    from django.utils.module_loading import autodiscover_modules  # type: ignore[attr-defined]

    if module_names is None:
        module_names = ["orchestrai", "ai"]

    autodiscover_modules(*module_names)
