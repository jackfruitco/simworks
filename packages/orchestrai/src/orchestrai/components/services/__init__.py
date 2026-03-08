"""Service components and helpers."""

from orchestrai.components.services.calls.mixins import ServiceCallMixin

from .calls import ServiceCall, assert_jsonable, to_jsonable
from .discovery import discover_services, list_services
from .exceptions import (
    MissingRequiredContextKeys,
    ServiceBuildRequestError,
    ServiceConfigError,
    ServiceDiscoveryError,
    ServiceDispatchError,
    ServiceError,
    ServiceStreamError,
)
from .registry import ServiceRegistry, ensure_service_registry, service_registry
from .service import BaseService, CoreTaskProxy, TaskDescriptor
from .task_proxy import ServiceSpec

__all__ = (
    "BaseService",
    "CoreTaskProxy",
    "MissingRequiredContextKeys",
    "ServiceBuildRequestError",
    "ServiceCall",
    "ServiceCallMixin",
    "ServiceConfigError",
    "ServiceDiscoveryError",
    "ServiceDispatchError",
    "ServiceError",
    "ServiceRegistry",
    "ServiceSpec",
    "ServiceStreamError",
    "TaskDescriptor",
    "assert_jsonable",
    "discover_services",
    "ensure_service_registry",
    "list_services",
    "service_registry",
    "to_jsonable",
)
