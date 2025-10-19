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
        bucket = "sim_responses"         # defaults to "default"
        name = "patient_initial_response"  # defaults to class name, snake-cased, with "Codec" suffix removed

**2) Parameterized form (explicit identity)**

    @codec(origin="chatlab", bucket="sim_responses", name="patient_initial_response")
    class PatientInitialResponseCodec(DjangoBaseLLMCodec):
        ...

Notes
-----
- The registry stores **classes**, not instances. A fresh codec instance is created per use.
- If bucket is omitted, it defaults to "default".
- Identities are canonical dot-form `origin.bucket.name` and tuple3 `(origin, bucket, name)` with snake_case normalization.
- This module re-exports the decorator via `simcore_ai_django.codecs.codec`.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Optional, Type, TypeVar

from simcore_ai.tracing import service_span_sync
from simcore_ai_django.identity import derive_django_identity_for_class, resolve_collision_django
from .base import DjangoBaseLLMCodec
from .registry import DjangoCodecRegistry

C = TypeVar("C", bound=Type[DjangoBaseLLMCodec])


def _register_class(codec_cls: Type[DjangoBaseLLMCodec], *, origin: str, bucket: str, name: str) -> Type[
    DjangoBaseLLMCodec]:
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


def codec(_cls: Optional[C] = None, *, origin: Optional[str] = None, bucket: Optional[str] = None,
          name: Optional[str] = None) -> Callable[[C], C] | C:
    """
    Decorate a DjangoBaseLLMCodec subclass to register it with a tuple3 identity.

    Usage:
        @codec
        class MyCodec(DjangoBaseLLMCodec): ...

        @codec(origin="chatlab", bucket="sim_responses", name="my_codec")
        class MyExplicitCodec(DjangoBaseLLMCodec): ...
    """

    def _wrap(cls: C) -> C:
        if not isinstance(cls, type) or not issubclass(cls, DjangoBaseLLMCodec):
            raise TypeError("@codec can only be applied to DjangoBaseLLMCodec subclasses")

        org, buck, nm = derive_django_identity_for_class(cls, origin=origin, bucket=bucket, name=name)

        def _exists(t: tuple[str, str, str]) -> bool:
            # Registry exposes a `has` or similar; if unavailable, fallback to safe dict check via private access.
            try:
                return DjangoCodecRegistry.has(*t)
            except Exception:
                # Fallback: inspect internal store if present
                store = getattr(DjangoCodecRegistry, "_store", {})
                return t in getattr(store, "keys", lambda: store.keys())()

        org, buck, nm = resolve_collision_django("codec", (org, buck, nm), exists=_exists)

        return _register_class(cls, origin=org, bucket=buck, name=nm)

    # No-arg usage: @codec
    if _cls is None:
        return _wrap

    # Parameterized usage: @codec(...)
    return _wrap(_cls)
