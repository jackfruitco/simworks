# orchestrai/app.py
"""A compact, explicit OrchestrAI application object.

The refactored app focuses on a predictable lifecycle:

1. ``configure``   -> apply settings from mappings/env/object
2. ``setup``       -> prepare loader and registries based on config (NO client/provider construction)
3. ``discover``    -> import configured discovery modules
4. ``finalize``    -> attach shared callbacks and freeze registries
5. ``start``/``run`` -> convenience wrapper performing the full flow

Client/provider construction is intentionally LAZY and happens on first access
(e.g. app.client / app.get_client()) so registered backends are available.
"""
from __future__ import annotations

import importlib
import sys
from collections.abc import Iterable
from collections.abc import Mapping as AbcMapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Callable

ORCA_BANNER = r"""...."""

from ._state import push_current_app, set_current_app
from .client.factory import build_orca_client
from .client.settings_loader import load_client_settings
from .conf.settings import Settings
from .finalize import consume_finalizers
from .fixups.base import Fixup, FixupStage
from .loaders.base import BaseLoader
from .registry import ComponentStore
from .registry.active_app import (
    flush_pending,
    push_active_registry_app,
    set_active_registry_app,
)


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
    fixups: list[Fixup] = field(default_factory=list)

    _default_client: str | None = None
    _configured: bool = False
    _finalized: bool = False
    _setup_done: bool = False
    _autodiscovered: bool = False
    _started: bool = False
    _banner_printed: bool = False
    _components_reported: bool = False
    _local_finalize_callbacks: list[Callable[[OrchestrAI], None]] = field(default_factory=list)
    _fixup_specs: list[object] = field(default_factory=list, repr=False)
    _ready_lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _booting: bool = False

    component_store: ComponentStore = field(default_factory=ComponentStore)

    # NOTE: these dicts hold either:
    #  - a concrete built instance (Any), OR
    #  - a definition mapping (dict) that will be built lazily later
    clients: dict[str, Any] = field(default_factory=dict)
    providers: dict[str, Any] = field(default_factory=dict)

    service_runners: dict[str, Any] = field(default_factory=dict)
    _service_finalize_callbacks: list[Callable[["OrchestrAI"], None]] = field(
        default_factory=list, repr=False
    )

    def __post_init__(self) -> None:
        # Capture any provided fixup specs; actual instances are built during configure
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
    def set_as_current(self) -> OrchestrAI:
        set_current_app(self)
        set_active_registry_app(self)
        return self

    def as_current(self):
        set_active_registry_app(self)
        return push_active_registry_app(self)

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def configure(self, mapping: dict | None = None, *, namespace: str | None = None) -> OrchestrAI:
        if mapping:
            self.conf.update_from_mapping(mapping, namespace=namespace)

        self._load_fixups_from_settings()
        self.apply_fixups(FixupStage.CONFIGURE_PRE)
        self._configured = True
        self.apply_fixups(FixupStage.CONFIGURE_POST)
        return self

    def config_from_object(self, obj: str, *, namespace: str | None = None) -> OrchestrAI:
        self.conf.update_from_object(obj, namespace=namespace)
        return self

    def config_from_envvar(
        self, envvar: str = "ORCHESTRAI_CONFIG_MODULE", *, namespace: str | None = None
    ) -> OrchestrAI:
        self.conf.update_from_envvar(envvar, namespace=namespace)
        return self

    def _ensure_configured(self) -> None:
        if not self._configured:
            self.configure()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def setup(self) -> OrchestrAI:
        self._ensure_configured()
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

        # IMPORTANT: normalize config only (NO backend resolution/build here)
        self._configure_clients()
        self._configure_providers()
        self._refresh_identity_strip_tokens()

        flush_pending(self.component_store)

        self._setup_done = True
        return self

    def discover(self) -> OrchestrAI:
        if self._finalized:
            return self
        self.setup()
        return self.autodiscover_components()

    def ensure_ready(self) -> OrchestrAI:
        """Ensure discovery/finalization have completed without re-starting the app."""
        with self._ready_lock:
            if self._finalized or self._booting:
                return self
            self._booting = True
            try:
                self.apply_fixups(FixupStage.ENSURE_READY_PRE)
                self.start()
                self.apply_fixups(FixupStage.ENSURE_READY_POST)
            finally:
                self._booting = False
        return self

    def finalize(self) -> OrchestrAI:
        if self._finalized:
            return self

        self._ensure_configured()
        self.apply_fixups(FixupStage.FINALIZE_PRE)
        if not self._autodiscovered:
            self.autodiscover_components()

        flush_pending(self.component_store)

        callbacks: list[Callable[[OrchestrAI], None]] = []
        callbacks.extend(consume_finalizers())
        callbacks.extend(self._local_finalize_callbacks)
        for callback in callbacks:
            callback(self)

        for callback in tuple(self._service_finalize_callbacks):
            callback(self)

        self.component_store.freeze_all()
        self._finalized = True
        self.print_component_report()
        self.apply_fixups(FixupStage.FINALIZE_POST)
        return self

    def start(self) -> OrchestrAI:
        if self._started:
            return self
        self._ensure_configured()
        self.apply_fixups(FixupStage.START_PRE)
        if not self._banner_printed:
            self.print_banner()
        self.setup()
        self.autodiscover_components()
        self.finalize()
        self._started = True
        self.apply_fixups(FixupStage.START_POST)
        return self

    run = start

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------
    def add_finalize_callback(self, callback: Callable[[OrchestrAI], None]) -> Callable[[OrchestrAI], None]:
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
    # Client/provider configuration (lazy)
    # ------------------------------------------------------------------
    @property
    def mode(self) -> str:
        return str(self.conf.get("MODE", "single"))

    def _configure_clients(self) -> None:
        # SINGLE MODE: store definition only; build lazily on access.
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

            # LAZY: do NOT call build_orca_client here.
            self.clients[name] = definition
            self._default_client = name
            return

        # POD MODE: already definition-driven; keep as-is.
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
        # Providers are also definitions (construction happens when used by client build)
        if self.mode == "single":
            return
        for name, definition in dict(self.conf.get("PROVIDERS", {})).items():
            self.providers[name] = definition

    def _refresh_identity_strip_tokens(self) -> None:
        """Compile and persist identity strip tokens onto app settings."""
        from .identity.utils import get_effective_strip_tokens

        with self.as_current():
            self.conf["IDENTITY_STRIP_TOKENS"] = get_effective_strip_tokens()

    # ------------------------------------------------------------------
    # Lazy client resolution
    # ------------------------------------------------------------------
    def get_client(self, name: str | None = None) -> Any | None:
        """
        Return a built client.

        If the stored value is a mapping definition, build the client on demand
        (after autodiscovery has run so provider backends are registered), then cache it.
        """
        if name is None:
            name = self._default_client
        if not name:
            return None

        existing = self.clients.get(name)
        if existing is None:
            return None

        # Already built (non-mapping)
        if not isinstance(existing, AbcMapping):
            return existing

        # Ensure discovery has happened before building clients that rely on registries.
        # This keeps Django/non-Django behavior consistent.
        if not self._autodiscovered and not self._finalized:
            self.autodiscover_components()

        settings = load_client_settings(self.conf)
        client = build_orca_client(settings, name)
        self.clients[name] = client
        return client

    def set_client(self, name: str, client: Any) -> None:
        self.clients[name] = client

    def set_default_client(self, name: str) -> None:
        self._default_client = name

    @property
    def client(self) -> Any | None:
        return self.get_client()

    # ------------------------------------------------------------------
    # Presentation helpers
    # ------------------------------------------------------------------
    def banner_text(self) -> str:
        """Return the stdout banner displayed when the app starts."""
        try:
            from importlib.metadata import version

            pkg_version = version("orchestrai")
        except Exception:  # pragma: no cover
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
        sections.append(f"- clients: {', '.join(client_names) if client_names else '<none>'}")
        sections.append(f"- providers: {', '.join(provider_names) if provider_names else '<none>'}")
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
    def add_fixup(self, spec: object) -> Fixup:
        if spec in self._fixup_specs:
            index = self._fixup_specs.index(spec)
            return self.fixups[index]

        fixup = self._resolve_fixup(spec)
        self._fixup_specs.append(spec)
        self.fixups.append(fixup)
        return fixup

    def apply_fixups(self, stage: FixupStage, **context: Any) -> list[Any]:
        results: list[Any] = []
        for fixup in self.fixups:
            result = fixup.apply(stage, self, **context)
            if result is not None:
                results.append(result)
        return results

    def _load_fixups_from_settings(self) -> None:
        specs: list[object] = []
        for spec in list(self._fixup_specs) + list(self.conf.get("FIXUPS", ())):
            if spec not in specs:
                specs.append(spec)

        self._fixup_specs = specs
        self.fixups = []
        for spec in specs:
            self.fixups.append(self._resolve_fixup(spec))

    def _resolve_fixup(self, spec: object) -> Fixup:
        if isinstance(spec, Fixup):
            return spec
        if isinstance(spec, str):
            obj = _import_string(spec)
            return self._coerce_fixup(obj, spec)
        return self._coerce_fixup(spec, spec)

    def _coerce_fixup(self, obj: object, label: object) -> Fixup:
        if isinstance(obj, Fixup):
            return obj
        if isinstance(obj, type):
            instance = obj()
            if isinstance(instance, Fixup):
                return instance
        if hasattr(obj, "apply"):
            return obj  # type: ignore[return-value]
        raise TypeError(f"Fixup path {label!r} did not resolve to a Fixup")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------
    def autodiscover_components(self) -> OrchestrAI:
        if self.loader is None or self._finalized or self._autodiscovered:
            return self

        self._ensure_configured()
        self.setup()

        modules: list[str] = list(self.conf.get("DISCOVERY_PATHS", ()))
        for extra in self.apply_fixups(FixupStage.AUTODISCOVER_PRE, modules=modules):
            if isinstance(extra, Iterable) and not isinstance(extra, (str, bytes)):
                modules.extend(extra)

        imported = self.loader.autodiscover(self, modules) or []
        self.apply_fixups(FixupStage.AUTODISCOVER_POST, modules=tuple(imported))
        self._autodiscovered = True
        return self


__all__ = ["OrchestrAI"]