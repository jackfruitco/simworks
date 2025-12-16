"""A compact, explicit OrchestrAI application object.

The refactored app focuses on a predictable lifecycle:

1. ``configure``   -> apply settings from mappings/env/object
2. ``setup``       -> prepare loader and registries based on config
3. ``discover``    -> import configured discovery modules
4. ``finalize``    -> attach shared callbacks and freeze registries
5. ``start``/``run`` -> convenience wrapper performing the full flow

The class intentionally avoids implicit discovery or networking at import
time. Users control the lifecycle explicitly.
"""
from __future__ import annotations

import importlib
import sys
from collections.abc import Mapping as AbcMapping
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


ORCA_BANNER = r"""
                      __
                  _.-'  `'-._
              _.-'          '-._
            .'    .-'''''-.     '.
           /    .'  .--.  '.      \
          /    /   (o  _)   \      \
         |     |    `-`      |      |
         |     \  .-'''''-.  /      /
          \     '.`.___.' .'      /
           '.      `---`       .'
             '-._          _.-'
                 `''----''`
             ~ jumping orca ~
"""

from ._state import push_current_app, set_current_app
from .conf.settings import Settings
from .finalize import consume_finalizers
from .fixups.base import BaseFixup
from .loaders.base import BaseLoader
from .registry import ComponentStore
from .registry.active_app import (
    flush_pending,
    push_active_registry_app,
    set_active_registry_app,
)
from .client.factory import build_orca_client
from .client.settings_loader import load_client_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_string(path: str):
    module_name, sep, attr = path.partition(":")
    if not sep:
        module_name, _, attr = path.rpartition(".")
    module = importlib.import_module(module_name)
    return getattr(module, attr) if attr else module


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

@dataclass
class OrchestrAI:
    name: str = "orchestrai"
    loader: BaseLoader | None = None
    conf: Settings = field(default_factory=Settings)
    fixups: list[BaseFixup] = field(default_factory=list)
    _default_client: str | None = None
    _finalized: bool = False
    _setup_done: bool = False
    _started: bool = False
    _banner_printed: bool = False
    _components_reported: bool = False
    _local_finalize_callbacks: list[Callable[["OrchestrAI"], None]] = field(default_factory=list)
    _fixup_specs: list[object] = field(default_factory=list, repr=False)

    component_store: ComponentStore = field(default_factory=ComponentStore)
    clients: dict[str, Any] = field(default_factory=dict)
    providers: dict[str, Any] = field(default_factory=dict)
    service_runners: dict[str, Any] = field(default_factory=dict)
    _service_finalize_callbacks: list[Callable[["OrchestrAI"], None]] = field(
        default_factory=list, repr=False
    )

    def __post_init__(self) -> None:
        # Capture any provided fixup specs; actual instances are built during setup
        if self.fixups:
            self._fixup_specs.extend(self.fixups)
            self.fixups = []

        # Load user overrides from the default settings module and optional envvar
        self.conf.update_from_object("orchestrai.settings")
        self.conf.update_from_envvar()

        set_active_registry_app(self)

    # ------------------------------------------------------------------
    # Current app helpers
    # ------------------------------------------------------------------
    def set_as_current(self) -> "OrchestrAI":
        set_current_app(self)
        set_active_registry_app(self)
        return self

    def as_current(self):
        set_active_registry_app(self)
        return push_active_registry_app(self)

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def configure(self, mapping: dict | None = None, *, namespace: str | None = None) -> "OrchestrAI":
        if mapping:
            self.conf.update_from_mapping(mapping, namespace=namespace)
        return self

    def config_from_object(self, obj: str, *, namespace: str | None = None) -> "OrchestrAI":
        self.conf.update_from_object(obj, namespace=namespace)
        return self

    def config_from_envvar(self, envvar: str = "ORCHESTRAI_CONFIG_MODULE", *, namespace: str | None = None) -> "OrchestrAI":
        self.conf.update_from_envvar(envvar, namespace=namespace)
        return self

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def setup(self) -> "OrchestrAI":
        if self._setup_done:
            return self

        if self.mode == "single":
            if self.conf.get("CLIENTS"):
                raise ValueError("CLIENTS is not allowed in single mode; use a single CLIENT mapping")
            if self.conf.get("PROVIDERS"):
                raise ValueError("PROVIDERS is not allowed in single mode; embed provider config in CLIENT")

        if self.loader is None:
            loader_path = self.conf.get("LOADER")
            loader_cls = _import_string(loader_path)
            self.loader = loader_cls()

        self._configure_fixups()
        self._configure_clients()
        self._configure_providers()
        self._refresh_identity_strip_tokens()

        flush_pending(self.component_store)

        self._setup_done = True
        return self

    def discover(self) -> "OrchestrAI":
        if self._finalized:
            return self
        self.setup()
        return self.autodiscover_components()

    def ensure_ready(self) -> "OrchestrAI":
        """Ensure discovery/finalization have completed without re-starting the app."""

        if self._finalized:
            return self
        self.discover()
        self.finalize()
        return self

    def finalize(self) -> "OrchestrAI":
        if self._finalized:
            return self

        flush_pending(self.component_store)

        callbacks: list[Callable[["OrchestrAI"], None]] = []
        callbacks.extend(consume_finalizers())
        callbacks.extend(self._local_finalize_callbacks)
        for callback in callbacks:
            callback(self)

        for callback in tuple(self._service_finalize_callbacks):
            callback(self)

        self.component_store.freeze_all()
        self._finalized = True
        self.print_component_report()
        return self

    def start(self) -> "OrchestrAI":
        if self._started:
            return self
        if not self._banner_printed:
            self.print_banner()
        self.discover()
        self.finalize()
        self._started = True
        return self

    run = start

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------
    def add_finalize_callback(self, callback: Callable[["OrchestrAI"], None]) -> Callable[["OrchestrAI"], None]:
        self._local_finalize_callbacks.append(callback)
        return callback

    def add_service_finalize_callback(
        self, callback: Callable[["OrchestrAI"], None]
    ) -> Callable[["OrchestrAI"], None]:
        self._service_finalize_callbacks.append(callback)
        return callback

    def register_service_runner(self, name: str, runner: Any) -> Any:
        if name not in self.service_runners:
            self.service_runners[name] = runner
        return runner

    # ------------------------------------------------------------------
    # Client/provider configuration
    # ------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.conf.get("MODE", "single")

    def _configure_clients(self) -> None:
        if self.mode == "single":
            client_conf = self.conf.get("CLIENT")
            if client_conf is None:
                self._default_client = None
                return
            if not isinstance(client_conf, AbcMapping):
                raise TypeError("In single mode, CLIENT must be a mapping of client configuration")

            name = client_conf.get("name") or "default"
            definition = dict(client_conf)
            definition.setdefault("name", name)
            settings = load_client_settings(self.conf)
            client = build_orca_client(settings, name)
            self.clients[name] = client
            self._default_client = name
            return

        clients_conf = dict(self.conf.get("CLIENTS", {}))
        default_client = self.conf.get("CLIENT")
        if default_client and default_client not in clients_conf:
            clients_conf[default_client] = {"name": default_client}

        for name, definition in clients_conf.items():
            self.clients[name] = definition

        if default_client is None and clients_conf:
            default_client = next(iter(clients_conf))
        self._default_client = default_client

    def _configure_providers(self) -> None:
        if self.mode == "single":
            return
        for name, definition in dict(self.conf.get("PROVIDERS", {})).items():
            self.providers[name] = definition

    def _refresh_identity_strip_tokens(self) -> None:
        """Compile and persist identity strip tokens onto app settings."""

        from .identity.utils import get_effective_strip_tokens

        with self.as_current():
            self.conf["IDENTITY_STRIP_TOKENS"] = get_effective_strip_tokens()

    def set_client(self, name: str, client):
        self.clients[name] = client

    def set_default_client(self, name: str):
        self._default_client = name

    @property
    def client(self):
        if self._default_client is None:
            return None
        return self.clients.get(self._default_client)

    # ------------------------------------------------------------------
    # Presentation helpers
    # ------------------------------------------------------------------
    def banner_text(self) -> str:
        """Return the stdout banner displayed when the app starts."""

        try:
            from importlib.metadata import PackageNotFoundError, version

            pkg_version = version("orchestrai")
        except Exception:  # pragma: no cover - metadata may be missing in tests
            pkg_version = "unknown"

        header = f"OrchestrAI™ v{pkg_version}".strip()
        company_ = f"\nfrom Jackruit.co™".strip()
        copyright_ = f"© 2026".strip()
        return f"{ORCA_BANNER}\n{header}\n{company_}\n{copyright_}\n".rstrip() + "\n"

    def print_banner(self, file=None) -> None:
        if file is None:
            file = sys.stdout
        print(self.banner_text(), file=file)
        self._banner_printed = True

    def component_report_text(self) -> str:
        registry_items = self.component_store.items()
        sections = []
        for kind, registry in sorted(registry_items.items()):
            try:
                names = sorted(registry.labels())
            except Exception:
                names = []
            items = ", ".join(names) if names else "<none>"
            sections.append(f"- {kind}: {items}")

        client_names = sorted(self.clients.keys())
        provider_names = sorted(self.providers.keys())
        service_runners = sorted(self.service_runners.keys())
        sections.append(
            f"- service_runners: {', '.join(service_runners) if service_runners else '<none>'}"
        )
        sections.append(
            f"- clients: {', '.join(client_names) if client_names else '<none>'}"
        )
        sections.append(
            f"- providers: {', '.join(provider_names) if provider_names else '<none>'}"
        )
        lines = ["Registered components:"]
        lines.extend(sections)
        return "\n".join(lines) + "\n"

    def print_component_report(self, file=None) -> None:
        if self._components_reported:
            return
        if file is None:
            file = sys.stdout
        print(self.component_report_text(), file=file)
        self._components_reported = True

    # ------------------------------------------------------------------
    # Fixup helpers
    # ------------------------------------------------------------------
    def _configure_fixups(self) -> None:
        specs: list[object] = list(self._fixup_specs)
        specs.extend(self.conf.get("FIXUPS", ()))

        resolved: list[BaseFixup] = []
        for spec in specs:
            fixup = self._resolve_fixup(spec)
            fixup.on_app_init(self)
            resolved.append(fixup)

        self.fixups = resolved
        for fixup in self.fixups:
            fixup.on_setup(self)

    def _resolve_fixup(self, spec: object) -> BaseFixup:
        if isinstance(spec, BaseFixup):
            return spec
        if isinstance(spec, str):
            obj = _import_string(spec)
            if isinstance(obj, type) and issubclass(obj, BaseFixup):
                return obj()
            if isinstance(obj, BaseFixup):
                return obj
            raise TypeError(f"Fixup path {spec!r} did not resolve to a BaseFixup")
        if isinstance(spec, type) and issubclass(spec, BaseFixup):
            return spec()
        raise TypeError(f"Unsupported fixup spec: {spec!r}")

    def autodiscover_components(self) -> "OrchestrAI":
        if self.loader is None:
            return self

        modules: list[str] = list(self.conf.get("DISCOVERY_PATHS", ()))
        for fixup in self.fixups:
            extra = fixup.autodiscover_sources(self)
            if extra:
                modules.extend(extra)

        imported = self.loader.autodiscover(self, modules) or []
        for fixup in self.fixups:
            fixup.on_import_modules(self, imported)
        return self


__all__ = ["OrchestrAI"]
