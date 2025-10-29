from __future__ import annotations

from typing import Any, Optional, Union, Tuple, Type

from simcore_ai.identity.utils import parse_dot_identity

try:
    # Prefer core Identity if available
    from simcore_ai.identity import Identity
except Exception:  # pragma: no cover - optional import
    Identity = object  # type: ignore[misc,assignment]

from simcore_ai.types.dtos import LLMResponse
from simcore_ai.tracing import service_span_sync

from .base import DjangoBaseLLMCodec
from .registry import CodecRegistry as DjangoCodecRegistry


def _as_tuple3(value: Tuple[str, str, str]) -> Tuple[str, str, str]:
    """Normalize a (namespace, kind, name) tuple to lowercase/trimmed strings."""
    ns, kd, nm = value
    return (
        str(ns).strip().lower(),
        str(kd).strip().lower(),
        str(nm).strip().lower(),
    )


def _is_identity_like(obj: Any) -> bool:
    return obj is not None and all(hasattr(obj, attr) for attr in ("namespace", "kind", "name"))


def _identity_like_to_tuple3(obj: Any) -> Optional[Tuple[str, str, str]]:
    if not _is_identity_like(obj):
        return None
    ns = str(getattr(obj, "namespace", "")).strip().lower()
    kd = str(getattr(obj, "kind", "")).strip().lower()
    nm = str(getattr(obj, "name", "")).strip().lower()
    if not (ns and kd and nm):
        return None
    return ns, kd, nm


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
      - A **tuple3 identity**: (namespace, kind, name)
      - An **identity string**: "ns.kind.name" (dot-delimited; no colons)
      - An **Identity** object (namespace/kind/name attributes)
      - **None** → resolve from `response.codec_identity`, or fall back to the response's service identity

    Resolution order:
      1) class → instantiate
      2) instance → use directly
      3) tuple3 → registry lookup
      4) identity string / Identity → registry lookup
      5) None → resolve via response.codec_identity; if missing, use (resp.namespace, resp.kind|default, resp.name)

    Raises:
      - CodecNotFoundError if resolution fails
      - TypeError if `codec` is of an unexpected type
    """
    ctx = context or {}

    # Precompute identities for tracing
    service_identity = ".".join(
        x for x in
        (getattr(response, "namespace", None), getattr(response, "kind", None), getattr(response, "name", None)) if x
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
                resolved = DjangoCodecRegistry.resolve(identity=(ns, b, n))

            # 4) codec is an identity string or Identity object
            elif isinstance(codec, str) or _is_identity_like(codec):
                tuple3: Optional[Tuple[str, str, str]] = None
                if isinstance(codec, str):
                    try:
                        ns, kd, nm = parse_dot_identity(codec)
                        tuple3 = (ns.lower(), kd.lower(), nm.lower())
                    except Exception:
                        tuple3 = None
                else:
                    tuple3 = _identity_like_to_tuple3(codec)
                if tuple3 is not None:
                    resolved = DjangoCodecRegistry.resolve(identity=tuple3)

            # 5) codec is None → resolve via response
            elif codec is None:
                # Prefer explicit response codec identity
                tuple3: Optional[Tuple[str, str, str]] = None
                if resp_codec_identity:
                    try:
                        ns, kd, nm = parse_dot_identity(resp_codec_identity)
                        tuple3 = (ns.lower(), kd.lower(), nm.lower())
                    except Exception:
                        tuple3 = None
                    if tuple3 is not None:
                        cls = DjangoCodecRegistry.resolve(identity=tuple3)
                        if cls is not None:
                            resolved = cls
                # Fallback to service identity on the response
                if resolved is None:
                    ns = getattr(response, "namespace", None)
                    b = getattr(response, "kind", None) or "default"
                    n = getattr(response, "name", None)
                    if ns and n:
                        resolved = DjangoCodecRegistry.resolve(identity=(ns, b, n))

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
            from .registry import CodecRegistry as _R
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
                                getattr(instance, "kind", None),
                                getattr(instance, "name", None),
                        ) if x
                    ) or resp_codec_identity,
                },
        ):
            return instance.handle_response(response, context=ctx)


__all__ = ["execute_codec"]
