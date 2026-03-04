"""Service components and helpers."""

from orchestrai.components.services.calls.mixins import ExecutionLifecycleMixin, ServiceCallMixin

from .calls import ServiceCall, assert_jsonable, to_jsonable
from .discovery import discover_services, list_services
from .exceptions import (
    MissingRequiredContextKeys,
    ServiceBuildRequestError,
    ServiceCodecResolutionError,
    ServiceConfigError,
    ServiceDiscoveryError,
    ServiceDispatchError,
    ServiceError,
    ServiceStreamError,
)
from .registry import ServiceRegistry, ensure_service_registry, service_registry
from .service import BaseService, CoreTaskProxy, TaskDescriptor
from .task_proxy import ServiceSpec

# Backward compatibility alias - PydanticAIService is now BaseService
PydanticAIService = BaseService

__all__ = (
    "BaseService",
    "CoreTaskProxy",
    "ExecutionLifecycleMixin",
    "MissingRequiredContextKeys",
    "PydanticAIService",  # Alias for backward compatibility
    "ServiceBuildRequestError",
    "ServiceCall",
    "ServiceCallMixin",
    "ServiceCodecResolutionError",
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
