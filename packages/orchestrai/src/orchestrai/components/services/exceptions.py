from __future__ import annotations

from collections.abc import Iterable

from orchestrai.exceptions.base import SimCoreError

__all__ = [
    "MissingRequiredContextKeys",
    "ServiceBuildRequestError",
    "ServiceConfigError",
    "ServiceDiscoveryError",
    "ServiceDispatchError",
    "ServiceError",
    "ServiceStreamError",
]


class ServiceError(SimCoreError):
    """Base class for service-related errors."""


class ServiceConfigError(ServiceError):
    """Configuration-time error for a service (misconfiguration, missing settings, etc.)."""


class MissingRequiredContextKeys(ServiceConfigError):
    """Raised when a service declares required context keys but they are absent."""

    def __init__(
        self,
        *,
        service: str,
        required_keys: Iterable[str],
        missing_keys: Iterable[str],
        context_keys: Iterable[str] | None = None,
    ) -> None:
        required = tuple(str(k) for k in required_keys)
        missing = tuple(str(k) for k in missing_keys)
        present = tuple(str(k) for k in (context_keys or ()))
        msg = (
            f"Missing required context keys for {service}: {missing}. "
            f"Required={required}; Present={present}"
        )
        super().__init__(msg)
        self.service = service
        self.required_keys = required
        self.missing_keys = missing
        self.context_keys = present


class ServiceBuildRequestError(ServiceError):
    """Raised when a service fails to build a valid backend-agnostic request."""


class ServiceStreamError(ServiceError):
    """Raised when a streaming operation fails (backend/client layer)."""


class ServiceDispatchError(ServiceError):
    """Raised when dispatching a service fails (missing runner, bad payload, etc.)."""


class ServiceDiscoveryError(ServiceError):
    """Raised when service discovery encounters an unrecoverable error."""
