from typing import Optional

from simcore_ai.codecs.exceptions import CodecNotFoundError
from simcore_ai.exceptions.base import SimCoreError


class ServiceError(SimCoreError): ...


class ServiceConfigError(ServiceError): ...


class ServiceCodecResolutionError(ServiceError, CodecNotFoundError):
    """
    Raised when a service cannot resolve a usable codec for execution.

    Parameters (all keyword-only)
    -----------------------------
    namespace: str
        The resolved namespace for the service (e.g., 'chatlab', 'simcore').
    kind: str
        The resolved kind/namespace for the service (e.g., 'default').
    name: str
        The resolved service leaf name (snake_case).
    codec: str | None
        The requested codec name, if any, or None when not specified.
    service: str
        The concrete service class name (for diagnostics).
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


class ServiceBuildRequestError(ServiceError): ...


class ServiceStreamError(ServiceError): ...
