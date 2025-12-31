"""Service components and helpers."""

from .calls import ServiceCall, assert_jsonable, to_jsonable
from .discovery import discover_services, list_services
from .execution import ExecutionLifecycleMixin, ServiceCallMixin
from .exceptions import (
    MissingRequiredContextKeys,
    ServiceBuildRequestError,
    ServiceCodecResolutionError,
    ServiceConfigError,
    ServiceDispatchError,
    ServiceDiscoveryError,
    ServiceError,
    ServiceStreamError,
)
from .registry import ServiceRegistry, ensure_service_registry, service_registry
from .service import BaseService
from .task_proxy import CoreTaskProxy, ServiceSpec

__all__ = (
    "BaseService",
    "CoreTaskProxy",
    "ServiceSpec",
    "ServiceCall",
    "assert_jsonable",
    "to_jsonable",
    "ServiceCallMixin",
    "ExecutionLifecycleMixin",
    "discover_services",
    "list_services",
    "ServiceRegistry",
    "service_registry",
    "ensure_service_registry",
    "ServiceError",
    "ServiceConfigError",
    "ServiceCodecResolutionError",
    "ServiceBuildRequestError",
    "ServiceStreamError",
    "ServiceDispatchError",
    "ServiceDiscoveryError",
    "MissingRequiredContextKeys",
)
