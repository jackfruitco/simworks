# orchestrai_django/codecs/__init__.py
"""
Django integration layer for `orchestrai.codecs`.

This package extends the core `orchestrai.codecs` system with Django-specific
behaviors for persistence, signal emission, and registry management.

Main components
---------------
- **DjangoBaseCodec** – Abstract base class implementing the codec pipeline:
  validate → restructure → persist (atomic) → emit.
- **codec** – Class decorator that registers codecs using a tuple4 identity
  `(domain, namespace, group, name)`. Supports both `@codec` and `@codec(namespace=..., ...)`.
- **CodecRegistry** – Central registry storing codec *classes*, keyed by
  their tuple4 identity. Used internally by services and executors.
- **get_codec** – Convenience access to the registry lookup.

Conventions
-----------
- Identities are normalized to lowercase snake_case.
- group defaults to `"default"` with a DeprecationWarning.
- Each codec class is registered, not instantiated; instances are created per-use.

Example
-------
    from orchestrai_django.codecs import codec, DjangoBaseCodec

    @codec(namespace="chatlab", group="sim_responses")
    class PatientInitialResponseCodec(DjangoBaseCodec):
        response_schema = PatientInitialOutputSchema

        def persist(self, *, resp, structured=None, **ctx):
            # Write ORM records here (atomic, idempotent)
            ...

This package provides the entrypoint most apps should import when
working with Django-aware codecs.
"""
from .codec import DjangoBaseCodec

__all__ = [
    "DjangoBaseCodec",
]
