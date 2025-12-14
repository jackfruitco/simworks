# orchestrai_django/integration.py

from typing import Any

from orchestrai.client.settings_loader import OrcaSettings, load_orca_settings
from orchestrai.conf.settings import Settings


def configure_from_django_settings(app: Any | None = None, *, namespace: str = "ORCA") -> OrcaSettings:
    """Load namespaced settings from ``django.conf.settings``."""

    from django.conf import settings as dj_settings  # type: ignore[attr-defined]

    conf = Settings()
    conf.update_from_mapping(vars(dj_settings), namespace=namespace)

    loaded = load_orca_settings(conf.as_dict())
    if app is not None and hasattr(app, "configure"):
        app.configure(conf.as_dict(), namespace=None)
    return loaded


def django_autodiscover(app: Any, *, module_names: list[str] | None = None) -> None:
    """
    Django-native autodiscovery. Imports module_names across INSTALLED_APPS.

    Defaults match core: ["orchestrai", "ai"].
    """
    from django.utils.module_loading import autodiscover_modules  # type: ignore[attr-defined]

    if module_names is None:
        module_names = ["orchestrai", "ai"]

    autodiscover_modules(*module_names)

    # Registration should happen via decorators/registries during import.
    # Optionally, if you have an explicit registry you can sync it onto app.components here.