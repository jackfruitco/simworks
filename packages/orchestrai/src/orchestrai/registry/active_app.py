"""Registry-aware active app helpers."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Generator

from orchestrai.utils.proxy import Proxy

from .component_store import ComponentStore
from .pending import PendingRegistrations
from .records import RegistrationRecord

_active_app: ContextVar[Any | None] = ContextVar("orca_registry_app", default=None)
_pending = PendingRegistrations()


def _infer_kind_from_type(component_type: type[Any]) -> str | None:
    try:
        from orchestrai.components.services.service import BaseService as _BaseService
        from orchestrai.components.codecs.codec import BaseCodec as _BaseCodec
        from orchestrai.components.schemas import BaseOutputSchema as _BaseOutputSchema
        from orchestrai.components.promptkit.base import PromptSection as _PromptSection
        from orchestrai.components.providerkit import BaseProvider as _BaseProvider
    except Exception:
        return None

    if issubclass(component_type, _BaseService):
        return "service"
    if issubclass(component_type, _BaseCodec):
        return "codec"
    if issubclass(component_type, _BaseOutputSchema):
        return "schema"
    if issubclass(component_type, _PromptSection):
        return "prompt_section"
    if issubclass(component_type, _BaseProvider):
        return "backend"
    return None


def set_active_registry_app(app: Any) -> None:
    _active_app.set(app)
    store = getattr(app, "component_store", None)
    if isinstance(store, ComponentStore):
        flush_pending(store)


@contextmanager
def push_active_registry_app(app: Any) -> Generator[Any, None, None]:
    token = _active_app.set(app)
    try:
        yield app
    finally:
        _active_app.reset(token)


def get_active_app() -> Any | None:
    app = _active_app.get()
    if app is not None:
        return app

    try:
        from orchestrai._state import get_current_app

        app = get_current_app()
        if app is not None:
            set_active_registry_app(app)
        return app
    except Exception:
        return None


def get_component_store(app: Any | None = None) -> ComponentStore | None:
    app = app or get_active_app()
    store = getattr(app, "component_store", None)
    if isinstance(store, ComponentStore):
        return store
    return None


def flush_pending(store: ComponentStore | None = None) -> None:
    store = store or get_component_store()
    if store is None:
        return
    _pending.flush_into(store)


def route_registration(record: RegistrationRecord) -> None:
    store = get_component_store()
    if store is None:
        _pending.enqueue(record)
        return
    store.register(record)


def get_registry_for(component: type[Any] | str) -> Any | None:
    store = get_component_store()
    if store is None:
        return None

    kind = component if isinstance(component, str) else _infer_kind_from_type(component)
    if kind is None:
        return None
    return store.registry(kind)


def registry_proxy(kind: str) -> Proxy:
    return Proxy(lambda: get_component_store().registry(kind))


# Public proxies for common kinds
services = registry_proxy("service")
codecs = registry_proxy("codec")
schemas = registry_proxy("schema")
prompt_sections = registry_proxy("prompt_section")
provider_backends = registry_proxy("backend")
providers = registry_proxy("provider")


__all__ = [
    "codecs",
    "flush_pending",
    "get_active_app",
    "get_component_store",
    "get_registry_for",
    "prompt_sections",
    "provider_backends",
    "providers",
    "registry_proxy",
    "route_registration",
    "schemas",
    "services",
    "set_active_registry_app",
    "push_active_registry_app",
]
