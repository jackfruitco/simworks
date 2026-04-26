from __future__ import annotations

import yaml
from pathlib import Path

from django.apps import apps as django_apps
from django.core.exceptions import ImproperlyConfigured

from .schemas import ModifierCatalog

_cache: dict[str, ModifierCatalog] = {}


def _clear_cache() -> None:
    _cache.clear()


def load_lab_modifier_catalog(lab_type: str) -> ModifierCatalog:
    if lab_type in _cache:
        return _cache[lab_type]

    try:
        app_config = django_apps.get_app_config(lab_type)
    except LookupError as exc:
        raise ImproperlyConfigured(
            f"No Django app config found for lab_type={lab_type!r}. "
            "Ensure the app is in INSTALLED_APPS."
        ) from exc

    yaml_path = Path(app_config.path) / "modifiers.yaml"
    if not yaml_path.exists():
        raise ImproperlyConfigured(
            f"Modifier catalog not found at {yaml_path}. "
            f"Create apps/{lab_type}/modifiers.yaml."
        )

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ImproperlyConfigured(
            f"Malformed YAML in {yaml_path}: {exc}"
        ) from exc

    try:
        catalog = ModifierCatalog.model_validate(raw)
    except Exception as exc:
        raise ImproperlyConfigured(
            f"Invalid modifier catalog schema in {yaml_path}: {exc}"
        ) from exc

    if catalog.lab != lab_type:
        raise ImproperlyConfigured(
            f"Modifier catalog lab={catalog.lab!r} does not match "
            f"expected lab_type={lab_type!r} in {yaml_path}."
        )

    _cache[lab_type] = catalog
    return catalog
