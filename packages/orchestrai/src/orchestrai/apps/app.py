# orchestrai/apps/app.py

import threading
from dataclasses import dataclass, field
from typing import Any, Mapping

from .bootstrap import configure_orca, configure_orca_pod
from .conf.loader import SettingsLoader
from .conf.models import OrcaSettings
from .discovery import autodiscover


class OrcaMode(str):
    AUTO = "auto"
    SINGLE = "single_orca"
    POD = "orca_pod"


@dataclass(slots=True)
class OrcaAppConfig:
    """
    Configuration holder + resolver for an OrchestrAI app instance.

    - Collects settings from one or more sources.
    - Resolves them into a single merged OrcaSettings instance.
    - Exposes final merged settings at: AppConfig.SETTINGS
    """

    loader: SettingsLoader = field(default_factory=SettingsLoader)
    _settings: OrcaSettings | None = None

    def from_object(self, obj_path: str, *, namespace: str = "ORCA") -> None:
        self.loader.add_object_source(obj_path=obj_path, namespace=namespace)

    def from_mapping(self, mapping: Mapping[str, Any], *, namespace: str = "ORCA") -> None:
        self.loader.add_mapping_source(mapping=mapping, namespace=namespace)

    def from_env(self, *, namespace: str = "ORCA") -> None:
        self.loader.add_env_source(namespace=namespace)

    def add_component_dirs(self, dirs: list[str]) -> None:
        # Stored inside settings.DISCOVERY.extra_component_dirs
        self.loader.add_component_dirs(dirs)

    def add_discovery_modules(self, module_names: list[str]) -> None:
        # Stored inside settings.DISCOVERY.modules
        self.loader.add_discovery_modules(module_names)

    def resolve(self) -> OrcaSettings:
        self._settings = self.loader.resolve()
        return self._settings

    @property
    def SETTINGS(self) -> OrcaSettings:
        if self._settings is None:
            raise RuntimeError("OrchestrAI settings are not resolved yet. Call app.AppConfig.resolve() first.")
        return self._settings


class OrchestrAI:
    """
    Core OrchestrAI application object.

    Design goals:
    - No Django dependency.
    - Lazy/idempotent configuration and discovery.
    - Supports Django and non-Django deployments.

    Typical usage:
        app = OrchestrAI(name="myproj", mode=OrcaMode.AUTO)
        app.AppConfig.from_object("myproj.settings", namespace="ORCA")
        app.autoconfigure_orca()
        app.autodiscover_components()
    """

    def __init__(self, *, name: str | None = None, mode: str = OrcaMode.AUTO) -> None:
        self.name = name
        self.mode = mode

        self.AppConfig = OrcaAppConfig()

        # Runtime state (configured/discovered)
        self._configured = False
        self._discovered = False
        self._lock = threading.RLock()

        # These can be populated by bootstrap logic.
        self.providers: dict[str, Any] = {}
        self.clients: dict[str, Any] = {}
        self.components: dict[str, Any] = {}

    # --------------------------
    # Settings entry points
    # --------------------------

    def configure_from_object(self, obj_path: str, *, namespace: str = "ORCA") -> "OrchestrAI":
        self.AppConfig.from_object(obj_path, namespace=namespace)
        return self

    def configure_from_mapping(self, mapping: Mapping[str, Any], *, namespace: str = "ORCA") -> "OrchestrAI":
        self.AppConfig.from_mapping(mapping, namespace=namespace)
        return self

    def configure_from_env(self, *, namespace: str = "ORCA") -> "OrchestrAI":
        self.AppConfig.from_env(namespace=namespace)
        return self

    # --------------------------
    # Lazy / idempotent orchestration
    # --------------------------

    def ensure_settings(self) -> OrcaSettings:
        with self._lock:
            if getattr(self.AppConfig, "_settings", None) is None:
                return self.AppConfig.resolve()
            return self.AppConfig.SETTINGS

    def autoconfigure_orca(self) -> "OrchestrAI":
        """
        Configure providers + clients from settings. Idempotent.
        """
        with self._lock:
            if self._configured:
                return self

            settings = self.ensure_settings()

            mode = self._resolve_mode(settings)
            if mode == OrcaMode.SINGLE:
                configure_orca(app=self, settings=settings)
            elif mode == OrcaMode.POD:
                configure_orca_pod(app=self, settings=settings)
            else:
                # Should never happen; _resolve_mode returns SINGLE/POD
                raise RuntimeError(f"Unsupported OrchestrAI mode: {mode}")

            self._configured = True
            return self

    def autodiscover_components(self) -> "OrchestrAI":
        """
        Discover decorated components. Idempotent.

        Core autodiscovery is non-Django:
        - Imports a set of module names for a set of "apps"/packages.
        - Uses DISCOVERY.{apps, modules, extra_component_dirs, extra_modules}
        - Never requires Django.

        Django-specific discovery should be done in orchestrai_django and can still
        call into this method (it will also work), or bypass it and populate app.components.
        """
        with self._lock:
            if self._discovered:
                return self

            settings = self.ensure_settings()
            discovered = autodiscover(settings=settings)
            # `discovered` is just "what we imported"; actual component registration is expected
            # to occur via decorators/registries during module import.
            self.components.update(discovered.components)

            self._discovered = True
            return self

    def ensure_ready(self) -> "OrchestrAI":
        """
        Convenience: settings -> providers/clients -> discovery.
        """
        return self.autoconfigure_orca().autodiscover_components()

    # --------------------------
    # Internal helpers
    # --------------------------

    def _resolve_mode(self, settings: OrcaSettings) -> str:
        # Explicit mode on instance wins.
        if self.mode and self.mode != OrcaMode.AUTO:
            return self.mode

        # Else infer from settings.MODE
        if settings.MODE in (OrcaMode.SINGLE, OrcaMode.POD):
            return settings.MODE

        # Default fallback
        return OrcaMode.SINGLE
