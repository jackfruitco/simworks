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
- On collision, this decorator appends a hyphen-int suffix to the **name** (e.g., `name-2`, `name-3`, ...) and retries until success.
"""
from __future__ import annotations

import logging
from typing import Any

from simcore_ai.decorators.registration import BaseRegistrationDecorator

logger = logging.getLogger(__name__)


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
    def register(self, cls: type[Any], identity: tuple[str, str, str], **kwargs) -> None:
        """Register the codec class with tuple³ uniqueness and collision suffixing."""
        Registry, DuplicateCodecIdentityError = _get_registry_and_exc()
        if Registry is None:
            logger.debug("CodecRegistry unavailable; skipping registration for %s", getattr(cls, "__name__", cls))
            return

        origin, bucket, name = identity

        # Ensure the resolved identity is reflected on the class prior to registration
        setattr(cls, "origin", origin)
        setattr(cls, "bucket", bucket)
        setattr(cls, "name", name)
        # Optional convenience string form if the class uses it
        setattr(cls, "identity", f"{origin}.{bucket}.{name}")

        if not (origin and bucket and name):
            logger.debug(
                "Codec identity incomplete; skipping registration: origin=%r bucket=%r name=%r",
                origin, bucket, name
            )
            return

        while True:
            try:
                Registry.register(cls, replace=False)  # type: ignore[attr-defined]
                logger.info(
                    "Registered Codec (%s, %s, %s) -> %s",
                    origin,
                    bucket,
                    name,
                    getattr(cls, "__name__", str(cls)),
                )
                return
            except DuplicateCodecIdentityError:
                # Bump only the name portion with a numeric suffix and retry
                new_name = self._bump_suffix(name)
                logger.warning(
                    "Collision for Codec identity (%s, %s, %s); renamed to (%s, %s, %s)",
                    origin,
                    bucket,
                    name,
                    origin,
                    bucket,
                    new_name,
                )
                name = new_name
                setattr(cls, "name", name)
                setattr(cls, "identity", f"{origin}.{bucket}.{name}")


# Ready-to-use decorator instance
codec = CodecDecorator()

__all__ = ["codec", "CodecDecorator"]
