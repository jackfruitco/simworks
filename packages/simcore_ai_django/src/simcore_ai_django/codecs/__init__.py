# simcore_ai_django/codecs/__init__.py
"""
Django integration layer for `simcore_ai.codecs`.

This package extends the core `simcore_ai.codecs` system with Django-specific
behaviors for persistence, signal emission, and registry management.

Main components
---------------
- **DjangoBaseLLMCodec** – Abstract base class implementing the codec pipeline:
  validate → restructure → persist (atomic) → emit.
- **codec** – Class decorator that registers codecs using a tuple3 identity
  `(namespace, bucket, name)`. Supports both `@codec` and `@codec(namespace=..., ...)`.
- **DjangoCodecRegistry** – Central registry storing codec *classes*, keyed by
  their tuple3 identity. Used internally by services and executors.
- **get_codec** – Convenience access to the registry lookup.

Conventions
-----------
- Identities are normalized to lowercase snake_case.
- Bucket defaults to `"default"` with a DeprecationWarning.
- Each codec class is registered, not instantiated; instances are created per-use.

Example
-------
    from simcore_ai_django.codecs import codec, DjangoBaseLLMCodec

    @codec(namespace="chatlab", bucket="sim_responses")
    class PatientInitialResponseCodec(DjangoBaseLLMCodec):
        response_format_class = PatientInitialOutputSchema

        def persist(self, *, resp, structured=None, **ctx):
            # Write ORM records here (atomic, idempotent)
            ...

This package provides the entrypoint most apps should import when
working with Django-aware codecs.
"""
from .base import DjangoBaseLLMCodec
from .decorators import codec
from .registry import DjangoCodecRegistry, get_codec

__all__ = [
    "DjangoBaseLLMCodec",
    "DjangoCodecRegistry",
    "get_codec",
    # decorator
    "codec"
]
