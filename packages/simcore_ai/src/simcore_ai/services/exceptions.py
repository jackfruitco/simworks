from typing import Optional, Iterable

from simcore_ai.codecs.exceptions import CodecNotFoundError
from simcore_ai.exceptions.base import SimCoreError

__all__ = [
    "ServiceError",
    "ServiceConfigError",
    "ServiceCodecResolutionError",
    "ServiceBuildRequestError",
    "ServiceStreamError",
    "MissingRequiredContextKeys",
]


class ServiceError(SimCoreError): ...


class ServiceConfigError(ServiceError):
    """Configuration-time error for a service (misconfiguration, missing settings, etc.)."""
    ...


class ServiceCodecResolutionError(ServiceError, CodecNotFoundError):
    """
    Raised when a service cannot resolve a usable codec for execution.

    Parameters (all keyword-only)
    -----------------------------
    namespace: str
        The resolved namespace for the service (e.g., "chatlab").
    kind: str
        The resolved kind/bucket for the service (e.g., "default").
    name: str
        The resolved service leaf name (snake_case).
    codec: str | None
        The requested codec name (if any), or None when not specified.
    service: str
        The concrete service class name (for diagnostics).

    Notes
    -----
    The canonical service identity is dot-only: "namespace.kind.name".
    """

    def __init__(self, *, namespace: str, kind: str, name: str, codec: Optional[str], service: str):
        msg = (
            "Could not resolve service codec "
            f"(namespace={namespace!r}, kind={kind!r}, name={name!r}, "
            f"requested_codec={codec!r}, service={service})"
        )
        super().__init__(msg)
        # Attach context for callers/logs to inspect programmatically.
        self.namespace = namespace
        self.kind = kind
        self.name = name
        self.codec = codec
        self.service = service
        self.identity_str = f"{namespace}.{kind}.{name}"


class MissingRequiredContextKeys(ServiceConfigError):
    """Raised when a service declares required context keys but they are absent.

    Attributes
    ----------
    service: str
        The concrete service class name.
    required_keys: tuple[str, ...]
        The keys declared by the service as required.
    missing_keys: tuple[str, ...]
        The subset of required keys not found in the provided context.
    context_keys: tuple[str, ...]
        The keys that *were* present in the provided context (for debugging).
    """

    def __init__(
            self,
            *,
            service: str,
            required_keys: Iterable[str],
            missing_keys: Iterable[str],
            context_keys: Iterable[str] | None = None,
    ) -> None:
        req = tuple(str(k) for k in required_keys)
        mis = tuple(str(k) for k in missing_keys)
        have = tuple(str(k) for k in (context_keys or ()))
        msg = (
            f"Missing required context keys for {service}: {mis}. "
            f"Required={req}; Present={have}"
        )
        super().__init__(msg)
        self.service = service
        self.required_keys = req
        self.missing_keys = mis
        self.context_keys = have


class ServiceBuildRequestError(ServiceError):
    """Raised when a service fails to build a valid provider-agnostic request."""
    ...


class ServiceStreamError(ServiceError):
    """Raised when a streaming operation fails (provider/client layer)."""
    ...
