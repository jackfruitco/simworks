# simcore_ai_django/codecs/decorators.py
"""
Django codec registration decorator (tuple3 identity (origin, bucket, name); class-based registration).

This decorator **registers a DjangoBaseLLMCodec SUBCLASS (class, not instance)**
with the central Django codec registry using a **tuple3 identity**:
`(origin, bucket, name)`.

You can use it with or without parameters:

**1) No-arg form (identity inferred from class + module)**

    from simcore_ai_django.codecs import codec
    from .base import DjangoBaseLLMCodec

    @codec
    class PatientInitialResponseCodec(DjangoBaseLLMCodec):
        # Optional overrides (otherwise inferred)
        origin = "chatlab"            # defaults to app/module root, e.g. "chatlab"
        bucket = "sim_responses"         # defaults to "default" (with DeprecationWarning)
        name = "patient_initial_response"  # defaults to class name, snake-cased, with "Codec" suffix removed

**2) Parameterized form (explicit identity)**

    @codec(origin="chatlab", bucket="sim_responses", name="patient_initial_response")
    class PatientInitialResponseCodec(DjangoBaseLLMCodec):
        ...

Notes
-----
- The registry stores **classes**, not instances. A fresh codec instance is created per use.
- Bucket is **optional**. If omitted, we register with bucket="default" and emit a DeprecationWarning.
- Identities are normalized to lowercase snake_case.
- This module re-exports the decorator via `simcore_ai_django.codecs.codec`.
"""
from __future__ import annotations

from typing import Any, Callable, Optional, Type, TypeVar

import re
import warnings

from simcore_ai.tracing import service_span_sync

from .base import DjangoBaseLLMCodec
from .registry import DjangoCodecRegistry

C = TypeVar("C", bound=Type[DjangoBaseLLMCodec])

_SNAKE_RE_1 = re.compile(r"(.)([A-Z][a-z]+)")
_SNAKE_RE_2 = re.compile(r"([a-z0-9])([A-Z])")


def _snake(name: str) -> str:
    s = _SNAKE_RE_1.sub(r"\1_\2", name)
    s = _SNAKE_RE_2.sub(r"\1_\2", s)
    return s.replace("__", "_").strip("_").lower()


def _infer_origin_from_module(codec_cls: Type[DjangoBaseLLMCodec]) -> Optional[str]:
    """
    Infer app origin from the module path, using the root package segment.
    Example: 'chatlab.ai.codecs.sim_responses' -> 'chatlab'
    """
    mod = getattr(codec_cls, "__module__", "") or ""
    root = mod.split(".", 1)[0] if mod else None
    return (root or None)


def _normalize_identity(
    *,
    codec_cls: Type[DjangoBaseLLMCodec],
    origin: Optional[str],
    bucket: Optional[str],
    name: Optional[str],
) -> tuple[str, str, str]:
    # Prefer explicit args; fall back to class attributes; then infer from module; then default.
    origin_raw = (origin or getattr(codec_cls, "origin", None) or _infer_origin_from_module(codec_cls) or "default").strip()
    name_raw = name or getattr(codec_cls, "name", None)
    bucket_raw = bucket or getattr(codec_cls, "bucket", None)

    # Legacy "bucket:name" in name → parse (warn) when bucket not provided
    if name_raw and ":" in str(name_raw) and bucket is None:
        warnings.warn(
            "Decorator received legacy name='bucket:name'. Please pass bucket and name separately.",
            DeprecationWarning,
            stacklevel=3,
        )
        bucket_part, name_part = str(name_raw).split(":", 1)
        bucket_raw = bucket_part
        name_raw = name_part

    # Default name: class name (snake) with 'Codec' suffix removed
    if not name_raw:
        cls_name = codec_cls.__name__
        cls_name = re.sub(r"Codec$", "", cls_name)
        name_raw = _snake(cls_name)
    else:
        name_raw = _snake(str(name_raw))

    # Default bucket: "default" (warn)
    if not bucket_raw:
        warnings.warn(
            "No bucket provided for codec identity; defaulting to bucket='default'. "
            "Bucket is optional, but explicit categories are recommended.",
            DeprecationWarning,
            stacklevel=3,
        )
        bucket_raw = "default"

    org = _snake(origin_raw)
    buck = _snake(str(bucket_raw))
    nm = _snake(str(name_raw))
    return org, buck, nm


def _register_class(codec_cls: Type[DjangoBaseLLMCodec], *, origin: str, bucket: str, name: str) -> Type[DjangoBaseLLMCodec]:
    with service_span_sync(
        "ai.codec.register",
        attributes={
            "ai.codec": codec_cls.__name__,
            "ai.identity.codec": f"{origin}.{bucket}.{name}",
            "origin": origin,
            "bucket": bucket,
            "name": name,
        },
    ):
        # Annotate the class (helpful for logging/resolve)
        setattr(codec_cls, "origin", origin)
        setattr(codec_cls, "bucket", bucket)
        setattr(codec_cls, "name", name)
        # Register the CLASS (not an instance)
        DjangoCodecRegistry.register(origin, bucket, name, codec_cls)
    return codec_cls


def codec(_cls: Optional[C] = None, *, origin: Optional[str] = None, bucket: Optional[str] = None, name: Optional[str] = None) -> Callable[[C], C] | C:
    """
    Decorate a DjangoBaseLLMCodec subclass to register it with a tuple3 identity.

    Usage:
        @codec
        class MyCodec(DjangoBaseLLMCodec): ...

        @codec(origin="chatlab", bucket="sim_responses", name="my_codec")
        class MyExplicitCodec(DjangoBaseLLMCodec): ...

    Legacy (deprecated):
        @codec(origin="chatlab", name="sim_responses:my_codec")
        class LegacyCodec(DjangoBaseLLMCodec): ...
    """
    def _wrap(cls: C) -> C:
        if not isinstance(cls, type) or not issubclass(cls, DjangoBaseLLMCodec):
            raise TypeError("@codec can only be applied to DjangoBaseLLMCodec subclasses")

        org, buck, nm = _normalize_identity(codec_cls=cls, origin=origin, bucket=bucket, name=name)
        return _register_class(cls, origin=org, bucket=buck, name=nm)

    # No-arg usage: @codec
    if _cls is None:
        return _wrap

    # Parameterized usage: @codec(...)
    return _wrap(_cls)