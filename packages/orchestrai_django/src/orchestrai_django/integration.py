# orchestrai_django/integration.py

from typing import Any

from orchestrai.apps.conf.models import OrcaSettings


def configure_from_django_settings(app: Any, *, namespace: str = "ORCA") -> OrcaSettings:
    """
    Load settings via django.conf.settings without forcing core orchestrai to depend on Django.
    """
    from django.conf import settings as dj_settings  # type: ignore[attr-defined]

    app.AppConfig.from_object("django.conf:settings", namespace=namespace)
    # In case user wants a dict-style ORCA config only:
    # (already handled by core loader's _extract_namespaced_settings)
    return app.ensure_settings()


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