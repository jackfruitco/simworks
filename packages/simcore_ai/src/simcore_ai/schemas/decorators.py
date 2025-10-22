# simcore_ai/schemas/decorators.py
"""Core (non-Django) response schema decorator built on the class-based base decorator.

This module defines the **core** `response_schema` decorator using the shared,
framework-agnostic `BaseRegistrationDecorator`. It supports decorating
**classes only** (schemas must be class types). Function targets will raise.

Identity resolution is provided by the base decorator:
- origin: first module segment or "simcore"
- bucket: second module segment or "default"
- name:   snake_case(class name with common affixes removed), with additional
          affix tokens merged from the core environment variable
          `SIMCORE_AI_IDENTITY_STRIP_TOKENS`.

Registration policy:
- Attempt to register the schema class with `ResponseSchemaRegistry.register(schema_cls)`.
- The registry is expected to enforce tuple³ uniqueness (origin, bucket, name)
  by raising `DuplicateResponseSchemaIdentityError` on collision.
- On collision, this decorator appends a hyphen-int suffix to the **name**
  (e.g., `name-2`, `name-3`, ...) and retries until success.
- Collisions are logged at WARNING level; import-time must never crash.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, NoReturn

from simcore_ai.decorators.registration import BaseRegistrationDecorator

log = logging.getLogger(__name__)


def _get_registry_and_exc():
    """Import ResponseSchemaRegistry and its duplicate error lazily and safely."""
    try:
        from simcore_ai.schemas.registry import ResponseSchemaRegistry  # type: ignore
    except Exception:  # pragma: no cover - resilient import
        ResponseSchemaRegistry = None  # type: ignore[assignment]
    try:
        from simcore_ai.schemas.registry import DuplicateResponseSchemaIdentityError  # type: ignore
    except Exception:  # pragma: no cover
        class DuplicateResponseSchemaIdentityError(Exception):  # type: ignore[no-redef]
            """Fallback duplicate error to keep the collision loop working."""
            pass
    return ResponseSchemaRegistry, DuplicateResponseSchemaIdentityError


class ResponseSchemaDecorator(BaseRegistrationDecorator):
    """Response schema decorator that supports class targets and collision-safe registration."""

    # --- functions are not supported for schemas ---
    def wrap_function(self, func: Callable[..., Any]) -> NoReturn:  # type: ignore[override]
        raise TypeError(
            "The `@response_schema` decorator only supports class targets; "
            f"got callable {func!r}"
        )

    # --- register---
    def register(self, cls, identity, **kwargs):
        """No-op; no schema registry."""
        pass


# Ready-to-use decorator instance
response_schema = ResponseSchemaDecorator()

__all__ = ["response_schema", "ResponseSchemaDecorator"]
