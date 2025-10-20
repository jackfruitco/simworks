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

    # --- register with collision handling ---
    def register(self, obj: Any) -> None:  # type: ignore[override]
        """Register the schema class with tuple³ uniqueness and collision suffixing."""
        Registry, DuplicateResponseSchemaIdentityError = _get_registry_and_exc()
        if Registry is None:
            log.debug("ResponseSchemaRegistry unavailable; skipping registration for %s", getattr(obj, "__name__", obj))
            return

        origin = getattr(obj, "origin", None)
        bucket = getattr(obj, "bucket", None)
        base_name = getattr(obj, "name", None)

        if not (origin and bucket and base_name):
            log.debug(
                "Response schema identity incomplete; skipping registration: origin=%r bucket=%r name=%r",
                origin, bucket, base_name
            )
            return

        suffix = 1
        while True:
            try:
                Registry.register(obj)  # type: ignore[attr-defined]
                log.info(
                    "Registered response schema: (%s, %s, %s) -> %s",
                    origin, bucket, getattr(obj, "name", base_name), getattr(obj, "__name__", obj),
                )
                return
            except DuplicateResponseSchemaIdentityError:
                suffix += 1
                new_name = f"{base_name}-{suffix}"
                setattr(obj, "name", new_name)
                log.warning(
                    "Collision for response schema identity (%s, %s, %s); renamed to (%s, %s, %s)",
                    origin, bucket, base_name,
                    origin, bucket, new_name,
                )
                # retry with updated name
            except Exception:  # pragma: no cover - registry-specific non-fatal errors
                log.debug("Response schema registration error suppressed for %s", getattr(obj, "__name__", obj),
                          exc_info=True)
                return


# Ready-to-use decorator instance
response_schema = ResponseSchemaDecorator()

__all__ = ["response_schema", "ResponseSchemaDecorator"]
