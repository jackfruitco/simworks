# simcore_ai_django/codecs/entrypoint.py
from __future__ import annotations

from typing import Any, Optional, Union, Tuple, Type

import warnings

try:
    # Prefer core Identity if available
    from simcore_ai.identity import Identity
except Exception:  # pragma: no cover - optional import
    Identity = object  # type: ignore[misc,assignment]

from simcore_ai.types.dtos import LLMResponse
from simcore_ai.tracing import service_span_sync

from .base import DjangoBaseLLMCodec
from .registry import DjangoCodecRegistry


def _as_tuple3(value: Tuple[str, str, str]) -> Tuple[str, str, str]:
    ns, b, n = value
    return (str(ns).strip().lower(), str(b).strip().lower(), str(n).strip().lower())


def _is_identity_like(obj: Any) -> bool:
    return all(hasattr(obj, attr) for attr in ("namespace", "bucket", "name"))


def execute_codec(
    codec: Union[
        Type[DjangoBaseLLMCodec],
        DjangoBaseLLMCodec,
        Tuple[str, str, str],
        str,
        Identity,
        None,
    ],
    response: LLMResponse,
    *,
    context: Optional[dict[str, Any]] = None,
) -> Any:
    """Execute a Django-aware codec end-to-end (validate → restructure → persist → emit).

    Accepted `codec` inputs:
      - A **codec class** (subclass of DjangoBaseLLMCodec) → will be instantiated
      - A **codec instance** (DjangoBaseLLMCodec)
      - A **tuple3 identity**: (namespace, bucket, name)
      - An **identity string**: "ns.bucket.name" or "ns:bucket:name"
      - An **Identity** object (namespace/bucket/name attributes)
      - **None** → resolve from `response.codec_identity`, or fall back to the response's service identity

    Resolution order:
      1) class → instantiate
      2) instance → use directly
      3) tuple3 → registry lookup
      4) identity string / Identity → registry lookup
      5) None → resolve via response.codec_identity; if missing, use (resp.namespace, resp.bucket|default, resp.name)

    Raises:
      - CodecNotFoundError if resolution fails
      - TypeError if `codec` is of an unexpected type
    """
    ctx = context or {}

    # Precompute identities for tracing
    service_identity = ".".join(
        x for x in (getattr(response, "namespace", None), getattr(response, "bucket", None), getattr(response, "name", None)) if x
    ) or None
    resp_codec_identity = getattr(response, "codec_identity", None)

    with service_span_sync(
        "ai.codec.execute",
        attributes={
            "ai.identity.service": service_identity,
            "ai.identity.codec": resp_codec_identity,
            "resp.correlation_id": getattr(response, "correlation_id", None),
            "resp.request_correlation_id": getattr(response, "request_correlation_id", None),
        },
    ):
        resolved: Union[DjangoBaseLLMCodec, Type[DjangoBaseLLMCodec], None] = None

        with service_span_sync("ai.codec.resolve"):
            # 1) codec is a CLASS
            if isinstance(codec, type) and issubclass(codec, DjangoBaseLLMCodec):
                resolved = codec

            # 2) codec is an INSTANCE
            elif isinstance(codec, DjangoBaseLLMCodec):
                resolved = codec

            # 3) codec is a tuple3 identity
            elif isinstance(codec, tuple) and len(codec) == 3:
                ns, b, n = _as_tuple3(codec)  # type: ignore[arg-type]
                resolved = DjangoCodecRegistry.get_codec(ns, b, n)

            # 4) codec is an identity string or Identity object
            elif isinstance(codec, str) or _is_identity_like(codec):
                # Try full identity first (ns.bucket.name / ns:bucket:name)
                cls = DjangoCodecRegistry.get_by_identity(codec)  # type: ignore[arg-type]
                if cls is not None:
                    resolved = cls
                else:
                    # Legacy "bucket:name" without namespace → infer namespace from response
                    if isinstance(codec, str) and (":" in codec and codec.count(":") == 1):
                        ns = getattr(response, "namespace", None)
                        if ns:
                            warnings.warn(
                                "Using legacy 'bucket:name' without namespace; inferring namespace from response.identity",
                                DeprecationWarning,
                                stacklevel=2,
                            )
                            bucket, name = codec.split(":", 1)
                            resolved = DjangoCodecRegistry.get_codec(ns, bucket, name)

            # 5) codec is None → resolve via response
            elif codec is None:
                # Prefer explicit response codec identity
                if resp_codec_identity:
                    cls = DjangoCodecRegistry.get_by_identity(resp_codec_identity)
                    if cls is not None:
                        resolved = cls
                # Fallback to service identity on the response
                if resolved is None:
                    ns = getattr(response, "namespace", None)
                    b = getattr(response, "bucket", None) or "default"
                    n = getattr(response, "name", None)
                    if ns and n:
                        resolved = DjangoCodecRegistry.get_codec(ns, b, n)

            else:
                raise TypeError("codec must be a class/instance/identity/tuple or None")

        # Instantiate if we resolved a class
        instance: Optional[DjangoBaseLLMCodec] = None
        if isinstance(resolved, type) and issubclass(resolved, DjangoBaseLLMCodec):
            instance = resolved()
        elif isinstance(resolved, DjangoBaseLLMCodec):
            instance = resolved

        if instance is None:
            # Build available list for the error message
            from .registry import DjangoCodecRegistry as _R
            available = ", ".join(sorted(_R.names())) or "<none>"
            from simcore_ai.codecs.exceptions import CodecNotFoundError
            raise CodecNotFoundError(
                f"Could not resolve codec for response. "
                f"Tried: codec={codec!r}, response.codec_identity={resp_codec_identity!r}, "
                f"response.identity={service_identity!r}. Available: {available}"
            )

        # Update tracing now that we know the codec identity/class
        with service_span_sync(
            "ai.codec.execute.resolved",
            attributes={
                "ai.codec": instance.__class__.__name__,
                "ai.identity.codec": ".".join(
                    x for x in (
                        getattr(instance, "namespace", None),
                        getattr(instance, "bucket", None),
                        getattr(instance, "name", None),
                    ) if x
                ) or resp_codec_identity,
            },
        ):
            return instance.handle_response(response, context=ctx)
