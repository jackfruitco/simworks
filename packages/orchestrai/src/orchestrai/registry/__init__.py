"""App-scoped component registries."""

from .active_app import (
    codecs,
    flush_pending,
    get_active_app,
    get_component_store,
    get_registry_for,
    prompt_sections,
    push_active_registry_app,
    registry_proxy,
    route_registration,
    schemas,
    services,
    set_active_registry_app,
)
from .base import BaseRegistry, ComponentRegistry
from .component_store import ComponentStore
from .pending import PendingRegistrations
from .records import RegistrationRecord

__all__ = [
    "BaseRegistry",
    "ComponentRegistry",
    "ComponentStore",
    "PendingRegistrations",
    "RegistrationRecord",
    "codecs",
    "flush_pending",
    "get_active_app",
    "get_component_store",
    "get_registry_for",
    "prompt_sections",
    "push_active_registry_app",
    "registry_proxy",
    "route_registration",
    "schemas",
    "services",
    "set_active_registry_app",
]
