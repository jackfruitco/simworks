# simcore_ai_django/codecs/execute.py
from __future__ import annotations

import inspect
from typing import Any, Optional, Union, Type, Awaitable, cast

from asgiref.sync import sync_to_async

from simcore_ai.identity import Identity, IdentityKey, coerce_identity_key
from simcore_ai.tracing import service_span_sync, flatten_context
from simcore_ai.types.dtos import LLMResponse
from .base import DjangoBaseLLMCodec
from .registry import CodecRegistry as DjangoCodecRegistry

CodecType = Type[DjangoBaseLLMCodec]
CodecInstanceOrType = Union[CodecType, DjangoBaseLLMCodec]
CodecResolvable = Union[CodecInstanceOrType, IdentityKey, None]


async def execute_codec(
        codec: CodecResolvable,
        response: LLMResponse,
        *,
        context: Optional[dict[str, Any]] = None,
) -> Any:
    """Async entrypoint to execute a Django-aware codec (validate → restructure → persist → emit).

    Identity handling is centralized:
      - If `codec` is a class or instance → use it directly.
      - Else if `codec` is an IdentityKey (tuple3 | dot string | Identity) → resolve via registry.
      - Else if `codec is None` → try response.codec_identity, then fallback to response (ns, kind, name).

    This function is **async-first**. If the resolved codec's `handle_response` is sync,
    it will be offloaded via `sync_to_async` automatically.
    """
    ctx = context or {}

    # Precompute identities for tracing
    service_identity = ".".join(
        x
        for x in (
            getattr(response, "namespace", None),
            getattr(response, "kind", None),
            getattr(response, "name", None),
        )
        if x
    ) or None
    resp_codec_identity = getattr(response, "codec_identity", None)

    _attrs = {
        "ai.identity.service": service_identity,
        "ai.identity.codec": resp_codec_identity,
        "resp.correlation_id": getattr(response, "correlation_id", None),
        "resp.request_correlation_id": getattr(response, "request_correlation_id", None),
        **flatten_context(ctx),
    }
    _attrs = {k: v for k, v in _attrs.items() if v is not None}

    with service_span_sync("ai.codec.execute", attributes=_attrs):
        resolved: Optional[CodecInstanceOrType] = None

        with service_span_sync("ai.codec.resolve"):
            # 1) codec is a CLASS
            if isinstance(codec, type) and issubclass(codec, DjangoBaseLLMCodec):
                resolved = codec

            # 2) codec is an INSTANCE
            elif isinstance(codec, DjangoBaseLLMCodec):
                resolved = codec

            # 3) codec is an IdentityKey (tuple3 | dot string | Identity)
            elif codec is not None:
                ident_tuple3 = coerce_identity_key(codec)
                if ident_tuple3 is not None:
                    resolved = DjangoCodecRegistry.get(ident_tuple3)

            # 4) codec is None → resolve via response hints
            else:
                # Prefer explicit response codec identity
                ident_tuple3 = coerce_identity_key(resp_codec_identity) if resp_codec_identity else None
                if ident_tuple3 is not None:
                    candidate_cls = DjangoCodecRegistry.get(ident_tuple3)
                    if candidate_cls is not None:
                        resolved = candidate_cls

                # Fallback to service identity on the response
                if resolved is None:
                    ns = getattr(response, "namespace", None)
                    kd = getattr(response, "kind", None) or "default"
                    nm = getattr(response, "name", None)
                    if ns and nm:
                        fallback_ident = (str(ns), str(kd), str(nm))
                        resolved = DjangoCodecRegistry.get(fallback_ident)

            if resolved is None:
                # Build available list for the error message
                from .registry import CodecRegistry as _R
                identities = getattr(_R, "identities", lambda: tuple())()
                available = ", ".join(".".join(t) for t in identities) or "<none>"

                from simcore_ai.codecs.exceptions import CodecNotFoundError

                raise CodecNotFoundError(
                    "Could not resolve codec for response. "
                    f"Tried: codec={codec!r}, response.codec_identity={resp_codec_identity!r}, "
                    f"response.identity={service_identity!r}. Available: {available}"
                )

        # Instantiate if we resolved a class
        instance: Optional[DjangoBaseLLMCodec] = None
        if isinstance(resolved, type) and issubclass(resolved, DjangoBaseLLMCodec):
            instance = resolved()
        elif isinstance(resolved, DjangoBaseLLMCodec):
            instance = resolved

        # Update tracing now that we know the codec identity/class
        codec_identity_str = None
        try:
            codec_identity_str = getattr(instance, "identity", None)
            if isinstance(codec_identity_str, Identity):
                codec_identity_str = codec_identity_str.as_str
            else:
                codec_identity_str = None
        except Exception:
            codec_identity_str = None

        with service_span_sync(
                "ai.codec.execute.resolved",
                attributes={
                    "ai.codec": instance.__class__.__name__ if instance else None,
                    "ai.identity.codec": codec_identity_str or resp_codec_identity,
                },
        ):
            # Execute the codec's handler (async-first; sync is offloaded)
            handler = getattr(instance, "handle_response")
            if inspect.iscoroutinefunction(handler):
                return await cast(Awaitable[Any], handler(response, context=ctx))
            return await sync_to_async(handler)(response, context=ctx)


__all__ = ["execute_codec"]
