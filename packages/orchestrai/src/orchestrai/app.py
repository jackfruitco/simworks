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
import warnings
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence


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
from .loaders.base import BaseLoader
from .registry.simple import Registry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import_string(path: str):
    module_name, sep, attr = path.partition(":")
    if not sep:
        module_name, _, attr = path.rpartition(".")
    module = importlib.import_module(module_name)
    return getattr(module, attr) if attr else module


_APPS_DEPRECATION = (
    "'orchestrai.apps' is deprecated; import OrchestrAI from 'orchestrai' instead.\n"
    "Example: from orchestrai import OrchestrAI"
)


def warn_deprecated_apps_import(stacklevel: int = 2) -> None:
    """Emit a single deprecation warning for the legacy apps module."""

    if getattr(warn_deprecated_apps_import, "_already_warned", False):
        return
    with warnings.catch_warnings():
        warnings.simplefilter("always", DeprecationWarning)
        warnings.warn(_APPS_DEPRECATION, DeprecationWarning, stacklevel=stacklevel)
    warn_deprecated_apps_import._already_warned = True


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

@dataclass
class OrchestrAI:
    name: str = "orchestrai"
    loader: BaseLoader | None = None
    conf: Settings = field(default_factory=Settings)
    _default_client: str | None = None
    _finalized: bool = False
    _setup_done: bool = False
    _started: bool = False
    _banner_printed: bool = False
    _components_reported: bool = False
    _local_finalize_callbacks: list[Callable[["OrchestrAI"], None]] = field(default_factory=list)

    services: Registry = field(default_factory=Registry)
    codecs: Registry = field(default_factory=Registry)
    providers: Registry = field(default_factory=Registry)
    clients: Registry = field(default_factory=Registry)
    prompt_sections: Registry = field(default_factory=Registry)

    # ------------------------------------------------------------------
    # Current app helpers
    # ------------------------------------------------------------------
    def set_as_current(self) -> "OrchestrAI":
        set_current_app(self)
        return self

    def as_current(self):
        return push_current_app(self)

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

        if self.loader is None:
            loader_path = self.conf.get("LOADER")
            loader_cls = _import_string(loader_path)
            self.loader = loader_cls()

        self._configure_clients()
        self._configure_providers()

        self._setup_done = True
        return self

    def discover(self) -> "OrchestrAI":
        if self._finalized:
            return self
        self.setup()
        if self.loader is None:
            return self
        modules: list[str] = list(self.conf.get("DISCOVERY_PATHS", ()))
        self.loader.autodiscover(self, modules)
        return self

    def finalize(self) -> "OrchestrAI":
        if self._finalized:
            return self

        callbacks: list[Callable[["OrchestrAI"], None]] = []
        callbacks.extend(consume_finalizers())
        callbacks.extend(self._local_finalize_callbacks)
        for callback in callbacks:
            callback(self)

        for registry in (self.services, self.codecs, self.providers, self.clients, self.prompt_sections):
            registry.freeze()
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

    # ------------------------------------------------------------------
    # Client/provider configuration
    # ------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.conf.get("MODE", "single")

    def _configure_clients(self) -> None:
        clients_conf = dict(self.conf.get("CLIENTS", {}))
        default_client = self.conf.get("CLIENT")
        if default_client and default_client not in clients_conf:
            clients_conf[default_client] = {"name": default_client}

        for name, definition in clients_conf.items():
            self.clients.register(name, definition)

        if default_client is None and clients_conf:
            default_client = next(iter(clients_conf))
        self._default_client = default_client

    def _configure_providers(self) -> None:
        for name, definition in dict(self.conf.get("PROVIDERS", {})).items():
            self.providers.register(name, definition)

    def set_client(self, name: str, client):
        self.clients.register(name, client)

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

        header = f"ORCHESTRAI v{pkg_version}".strip()
        return f"{ORCA_BANNER}\n{header}\n".rstrip() + "\n"

    def print_banner(self, file=None) -> None:
        if file is None:
            file = sys.stdout
        print(self.banner_text(), file=file)
        self._banner_printed = True

    def component_report_text(self) -> str:
        sections = (
            ("services", self.services),
            ("providers", self.providers),
            ("clients", self.clients),
            ("codecs", self.codecs),
            ("prompt_sections", self.prompt_sections),
        )
        lines = ["Registered components:"]
        for label, registry in sections:
            names = sorted(registry.all().keys())
            items = ", ".join(names) if names else "<none>"
            lines.append(f"- {label}: {items}")
        return "\n".join(lines) + "\n"

    def print_component_report(self, file=None) -> None:
        if self._components_reported:
            return
        if file is None:
            file = sys.stdout
        print(self.component_report_text(), file=file)
        self._components_reported = True


__all__ = ["OrchestrAI"]
