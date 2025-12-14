"""Celery-inspired OrchestrAI application object."""

from __future__ import annotations

import importlib
from contextlib import contextmanager
from typing import Sequence

from ._state import push_current_app, set_current_app
from .conf.settings import Settings
from .finalize import consume_finalizers
from .fixups.base import BaseFixup
from .loaders.base import BaseLoader
from .registry.simple import Registry
from .utils.proxy import Proxy


def _maybe_import(path: str):
    module_name, sep, attr = path.partition(":")
    if not sep:
        module_name, _, attr = path.rpartition(".")
    module = importlib.import_module(module_name)
    return getattr(module, attr) if attr else module


class OrchestrAI:
    def __init__(self, name: str | None = None, loader: BaseLoader | None = None, fixups: Sequence[str] | None = None):
        self.name = name or "orchestrai"
        self.conf = Settings()
        self.loader: BaseLoader | None = loader
        self.fixups: list[BaseFixup] = []
        self._configured = False
        self._setup_done = False
        self._started = False
        self._finalized = False
        self._on_finalize: list[callable] = []
        self.configured_backends: set[str] = set()

        self.services = Registry()
        self.codecs = Registry()
        self.providers = Registry()
        self.clients = Registry()
        self.prompt_sections = Registry()
        self._default_client: str | None = None

        if fixups:
            self._install_fixups(fixups)
        for fixup in self.fixups:
            fixup.on_app_init(self)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _install_fixups(self, fixups: Sequence[str]):
        for path in fixups:
            fixup_cls = _maybe_import(path)
            fixup = fixup_cls() if isinstance(fixup_cls, type) else fixup_cls
            if isinstance(fixup, BaseFixup):
                self.fixups.append(fixup)

    # ------------------------------------------------------------------
    # Current app helpers
    # ------------------------------------------------------------------
    def set_as_current(self):
        set_current_app(self)
        return self

    @contextmanager
    def as_current(self):
        with push_current_app(self):
            yield self

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def config_from_object(self, obj: str, namespace: str | None = None):
        self.conf.update_from_object(obj, namespace=namespace)
        return self

    def config_from_envvar(self, envvar: str = "ORCHESTRAI_CONFIG_MODULE", namespace: str | None = None):
        self.conf.update_from_envvar(envvar, namespace=namespace)
        return self

    def load_from_conf(self, mapping: dict | None = None, namespace: str | None = None):
        if mapping:
            self.conf.update_from_mapping(mapping, namespace=namespace)
        else:
            self.config_from_envvar(namespace=namespace)
        return self

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def setup(self, autostart: bool = False):
        if self._setup_done:
            if autostart:
                return self.start()
            return self

        if self.loader is None:
            loader_cls = _maybe_import(self.conf.get("LOADER"))
            self.loader = loader_cls()

        self.loader.read_configuration(self)
        self._install_fixups(self.conf.get("FIXUPS", ()))
        for fixup in self.fixups:
            fixup.on_setup(self)

        self._configure_autoclient()
        if self.mode == "pod":
            self._configure_clients()
        self._configure_providers()
        self._setup_done = True

        if autostart:
            return self.start()
        return self

    def start(self):
        if self._started:
            return self
        self.setup()
        self.autodiscover_components()
        self.finalize()
        self._started = True
        return self

    def run(self):
        return self.start()

    def finalize(self):
        if self._finalized:
            return self
        callbacks = consume_finalizers() + list(self._on_finalize)
        for callback in callbacks:
            callback(self)
        self.services.freeze()
        self.codecs.freeze()
        self.providers.freeze()
        self.clients.freeze()
        self.prompt_sections.freeze()
        self._finalized = True
        return self

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def autodiscover_components(self):
        if self.loader is None:
            return self
        modules = list(self.conf.get("DISCOVERY_PATHS", ()))
        for fixup in self.fixups:
            modules.extend(list(fixup.autodiscover_sources(self)))
            fixup.on_import_modules(self, modules)
        self.loader.autodiscover(self, modules)
        return self

    # ------------------------------------------------------------------
    # Client/provider configuration
    # ------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return self.conf.get("MODE", "single")

    def _configure_autoclient(self):
        default_client = self.conf.get("CLIENT")
        if default_client:
            self.clients.register(default_client, {"name": default_client})
            clients_conf = self.conf.get("CLIENTS", {})
            definition = clients_conf.get(default_client, {"name": default_client})
            self.clients.register(default_client, definition)

    def _configure_clients(self):
        for name, definition in self.conf.get("CLIENTS", {}).items():
            if name not in self.clients:
                self.clients.register(name, definition)
        if self._default_client is None and self.conf.get("CLIENTS"):
            self._default_client = next(iter(self.conf.get("CLIENTS").keys()))

    def _configure_providers(self):
        for name, definition in self.conf.get("PROVIDERS", {}).items():
            if name not in self.providers:
                self.providers.register(name, definition)
                self.configured_backends.add(name)

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
    # Finalize callbacks
    # ------------------------------------------------------------------
    def add_finalize_callback(self, callback):
        self._on_finalize.append(callback)
        return callback

