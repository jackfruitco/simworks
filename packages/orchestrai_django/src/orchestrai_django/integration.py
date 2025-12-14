# orchestrai_django/integration.py

from __future__ import annotations

import importlib.util
from typing import Any, Iterable, Mapping

from orchestrai.conf.settings import Settings

COMPONENT_MODULES: tuple[str, ...] = (
    "services",
    "codecs",
    "schemas",
    "prompts",
    "prompt_sections",
    "tools",
    "types",
    "mixins",
)


def _coerce_mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return value
    raise TypeError("Django settings for OrchestrAI must be a mapping or None")


def _validate_single_mode(mapping: Mapping[str, Any]) -> None:
    mode = (mapping.get("MODE") or "single").lower()
    if mode != "single":
        return

    if "CLIENTS" in mapping or "PROVIDERS" in mapping:
        raise ValueError("SINGLE mode configuration must not include CLIENTS or PROVIDERS")

    client_conf = mapping.get("CLIENT")
    from collections.abc import Mapping as AbcMapping

    if not isinstance(client_conf, AbcMapping) or not client_conf:
        raise ValueError("SINGLE mode requires ORCA_CONFIG['CLIENT'] to be a non-empty mapping")


def _existing_modules_for_root(root: str) -> list[str]:
    discovered: list[str] = []
    try:
        if importlib.util.find_spec(root):
            discovered.append(root)
    except ModuleNotFoundError:
        return discovered

    for suffix in COMPONENT_MODULES:
        module_name = f"{root}.{suffix}"
        try:
            if importlib.util.find_spec(module_name):
                discovered.append(module_name)
        except ModuleNotFoundError:
            continue
    return discovered


def _build_discovery_paths(installed_apps: Iterable[str]) -> list[str]:
    paths: list[str] = []
    for app_label in installed_apps:
        for base in (f"{app_label}.orca", f"{app_label}.ai"):
            for module_name in _existing_modules_for_root(base):
                if module_name not in paths:
                    paths.append(module_name)
    return paths


def configure_from_django_settings(
    app: Any | None = None,
    *,
    namespace: str = "ORCA_CONFIG",
) -> Settings:
    """Load OrchestrAI configuration from ``django.conf.settings`` using the current API."""

    from django.conf import settings as dj_settings  # type: ignore[attr-defined]

    mapping = dict(_coerce_mapping(getattr(dj_settings, namespace, None)))
    _validate_single_mode(mapping)

    conf = Settings()
    conf.update_from_mapping(mapping)

    discovery_paths = list(mapping.get("DISCOVERY_PATHS", ()))
    discovery_paths.extend(_build_discovery_paths(getattr(dj_settings, "INSTALLED_APPS", ())))
    # Preserve order while deduping
    seen: set[str] = set()
    deduped_paths: list[str] = []
    for path in discovery_paths:
        if path and path not in seen:
            seen.add(path)
            deduped_paths.append(path)
    conf["DISCOVERY_PATHS"] = tuple(deduped_paths)

    if not conf.get("LOADER"):
        conf["LOADER"] = "orchestrai.loaders.default:DefaultLoader"

    if app is not None and hasattr(app, "configure"):
        app.configure(conf.as_dict())
    return conf


def django_autodiscover(app: Any, *, module_names: list[str] | None = None) -> None:
    """Django-native autodiscovery. Imports module_names across INSTALLED_APPS."""

    from django.utils.module_loading import autodiscover_modules  # type: ignore[attr-defined]

    if module_names is None:
        module_names = ["orca", "ai"]

    autodiscover_modules(*module_names)
