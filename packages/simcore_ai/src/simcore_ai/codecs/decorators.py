# simcore_ai/codecs/decorators.py
"""Core (non-Django) codec decorator built on the class-based base decorator.

This module defines the **core** `codec` decorator using the shared,
framework-agnostic `BaseRegistrationDecorator`. It supports decorating
**classes only** (codecs must be class types). Function targets will raise.

Identity resolution rules are provided by the base:
- origin: first module segment or "simcore"
- bucket: second module segment or "default"
- name:   snake_case(class name with common affixes removed), with additional
          affix tokens merged from the core environment variable
          `SIMCORE_AI_IDENTITY_STRIP_TOKENS`.

Registration policy:
- Attempt to register the codec class with `CodecRegistry.register(codec_cls, replace=False)`.
- The registry is expected to enforce tuple³ uniqueness (origin, bucket, name)
  by raising `DuplicateCodecIdentityError` on collision.
- On collision, this decorator appends a hyphen-int suffix to the **name**
  (e.g., `name-2`, `name-3`, ...) and retries until success.
- Collisions are logged at WARNING level; import-time must never crash.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, NoReturn
import logging

from simcore_ai.decorators.registration import BaseRegistrationDecorator

log = logging.getLogger(__name__)

# Lazy, import-safe references to the registry and duplicate exception.
# These imports are inside functions to avoid hard failures at import time
# if the registry package is not yet available.
def _get_registry_and_exc():
    try:
        from simcore_ai.codecs.registry import CodecRegistry  # type: ignore
    except Exception:  # pragma: no cover - keep safe across environments
        CodecRegistry = None  # type: ignore[assignment]
    try:
        from simcore_ai.codecs.registry import DuplicateCodecIdentityError  # type: ignore
    except Exception:  # pragma: no cover
        class DuplicateCodecIdentityError(Exception):  # type: ignore[no-redef]
            """Fallback duplicate error to keep the collision loop working."""
            pass
    return CodecRegistry, DuplicateCodecIdentityError


class CodecDecorator(BaseRegistrationDecorator):
    """Codec decorator that supports class targets, registration, and collisions."""

    # --- functions are not supported for codecs ---
    # def wrap_function(self, func: Callable[..., Any]) -> NoReturn:  # type: ignore[override]
    #     raise TypeError(
    #         "The `@codec` decorator only supports class targets; "
    #         f"got callable {func!r}"
    #     )

    # --- register with collision handling ---
    def register(self, obj: Any) -> None:  # type: ignore[override]
        """Register the codec class with tuple³ uniqueness and collision suffixing."""
        Registry, DuplicateCodecIdentityError = _get_registry_and_exc()
        if Registry is None:
            log.debug("CodecRegistry unavailable; skipping registration for %s", getattr(obj, "__name__", obj))
            return

        origin = getattr(obj, "origin", None)
        bucket = getattr(obj, "bucket", None)
        base_name = getattr(obj, "name", None)

        if not (origin and bucket and base_name):
            log.debug(
                "Codec identity incomplete; skipping registration: origin=%r bucket=%r name=%r",
                origin, bucket, base_name
            )
            return

        suffix = 1
        while True:
            try:
                Registry.register(obj, replace=False)  # type: ignore[attr-defined]
                log.info("Registered codec: (%s, %s, %s) -> %s", origin, bucket, getattr(obj, "name", base_name), getattr(obj, "__name__", obj))
                return
            except DuplicateCodecIdentityError:
                suffix += 1
                new_name = f"{base_name}-{suffix}"
                setattr(obj, "name", new_name)
                log.warning(
                    "Collision for codec identity (%s, %s, %s); renamed to (%s, %s, %s)",
                    origin, bucket, base_name,
                    origin, bucket, new_name,
                )
                # retry with updated name
            except Exception:  # pragma: no cover - registry-specific non-fatal errors
                log.debug("Codec registration error suppressed for %s", getattr(obj, "__name__", obj), exc_info=True)
                return


# Ready-to-use decorator instance
codec = CodecDecorator()

__all__ = ["codec", "CodecDecorator"]
