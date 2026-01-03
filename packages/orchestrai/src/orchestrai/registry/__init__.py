"""App-scoped component registries."""

from .active_app import (
    codecs,
    flush_pending,
    get_active_app,
    get_component_store,
    get_registry_for,
    prompt_sections,
    provider_backends,
    providers,
    registry_proxy,
    route_registration,
    schemas,
    services,
    set_active_registry_app,
    push_active_registry_app,
)
from .base import BaseRegistry, ComponentRegistry
from .component_store import ComponentStore
from .pending import PendingRegistrations
from .records import RegistrationRecord

__all__ = [
    "BaseRegistry",
    "ComponentRegistry",
    "ComponentStore",
    "RegistrationRecord",
    "PendingRegistrations",
    "services",
    "provider_backends",
    "providers",
    "codecs",
    "prompt_sections",
    "schemas",
    "registry_proxy",
    "set_active_registry_app",
    "push_active_registry_app",
    "get_registry_for",
    "get_active_app",
    "get_component_store",
    "route_registration",
    "flush_pending",
]
