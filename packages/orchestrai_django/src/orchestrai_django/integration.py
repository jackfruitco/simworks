# orchestrai_django/integration.py

from __future__ import annotations

import importlib
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


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _collect_mapping_from_settings(dj_settings: Any, namespace: str) -> dict[str, Any]:
    explicit = getattr(dj_settings, namespace, None)
    if explicit is not None:
        return dict(_coerce_mapping(explicit))

    # Namespaced attributes (e.g., ORCHESTRAI_CLIENT)
    prefix = f"{namespace}_"
    namespaced: dict[str, Any] = {}
    for name in dir(dj_settings):
        if not name.startswith(prefix):
            continue
        namespaced[name[len(prefix) :]] = getattr(dj_settings, name)
    if namespaced:
        return namespaced

    # Legacy fallback to ORCA_CONFIG for backwards compatibility
    legacy = getattr(dj_settings, "ORCA_CONFIG", None)
    if legacy is not None:
        return dict(_coerce_mapping(legacy))

    return {}


def configure_from_django_settings(
    app: Any | None = None,
    *,
    namespace: str = "ORCHESTRAI",
) -> Settings:
    """Load OrchestrAI configuration from ``django.conf.settings`` using the current API.

    Django's responsibility here is ONLY to compute DISCOVERY_PATHS from INSTALLED_APPS
    and inject it into the core Settings. Core OrchestrAI discovery imports everything
    uniformly via app.autodiscover_components().
    """
    from django.conf import settings as dj_settings  # type: ignore[attr-defined]

    mapping = _collect_mapping_from_settings(dj_settings, namespace)
    _validate_single_mode(mapping)

    conf = Settings()
    conf.update_from_mapping(mapping)

    # Ensure Django-backed service runners register finalize callbacks early.
    try:
        import orchestrai_django.components.service_runners.django_tasks  # noqa: F401
    except Exception:
        pass

    try:
        setattr(app, "default_service_runner", "django")
    except Exception:
        pass

    discovery_paths: list[str] = []
    discovery_paths.extend(conf.get("DISCOVERY_PATHS", ()))
    discovery_paths.extend(_build_discovery_paths(getattr(dj_settings, "INSTALLED_APPS", ())))
    conf["DISCOVERY_PATHS"] = tuple(_dedupe_preserve_order(discovery_paths))

    if app is not None and hasattr(app, "configure"):
        app.configure(conf.as_dict())
    return conf


class DjangoAdapter:
    """Adapter wiring Django settings into an OrchestrAI app.

    Note: We do NOT import modules here. We only populate Settings (incl. DISCOVERY_PATHS).
    Core OrchestrAI will import those paths during its normal autodiscover_components() flow.
    """

    def __init__(self, app: Any, *, namespace: str = "ORCHESTRAI") -> None:
        self.app = app
        self.namespace = namespace

    def configure(self) -> Settings:
        return configure_from_django_settings(self.app, namespace=self.namespace)

    def ensure_ready(self) -> Any:
        if hasattr(self.app, "ensure_ready"):
            return self.app.ensure_ready()
        return None