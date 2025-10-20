# simcore_ai/codecs/decorators.py
"""Core (non-Django) codec decorator built on the base decorator factory.

This module defines the **core** `codec` decorator using the shared dual-form
factory and the **default module-centric identity resolver**. It remains
framework-agnostic and does not import any Django modules.

Usage (dual-form):

    from simcore_ai.codecs.decorators import codec
    from simcore_ai.codecs import BaseLLMCodec

    @codec
    class PatientCodec(BaseLLMCodec):
        ...

    @codec(origin="chatlab", bucket="patient", name="default")
    class PatientCodecExplicit(BaseLLMCodec):
        ...

Identity defaults in core:
- origin: module root or "simcore"
- bucket: second module segment or "default"
- name:   snake_case(class name with common suffixes removed)

Registration:
- Attempts to register the **class** with `CodecRegistry.register`.
- If the core registry expects instances (legacy behavior), falls back to
  instantiating the class and registering the instance.
- Duplicate registrations (e.g., during autoreload) are tolerated.
- All registry calls are guarded to avoid import-time crashes if the registry
  is unavailable.
"""
from __future__ import annotations

import logging
from typing import Any, Type

from simcore_ai.decorators.base import (
    make_class_decorator,
    default_identity_resolver,
)

logger = logging.getLogger(__name__)


# Import inside helpers to avoid hard import failures if registry isn't present at import time

def _post_register_codec(codec_cls: Type[Any]) -> None:
    """Register the codec class (or instance, if required by legacy core registry).

    This helper is resilient to different registry signatures and import-time
    availability. It logs and tolerates duplicate registrations.
    """
    try:
        from simcore_ai.codecs.registry import CodecRegistry
        try:
            # Preferred: class-based registration (consistent with Django layer)
            CodecRegistry.register(codec_cls)
            logger.info(
                "Registered codec class: %s.%s.%s (%s)",
                getattr(codec_cls, "origin", "?"),
                getattr(codec_cls, "bucket", "?"),
                getattr(codec_cls, "name", "?"),
                codec_cls.__name__,
            )
            return
        except TypeError:
            # Fallback: legacy instance-based registration
            try:
                instance = codec_cls()  # shallow construct for legacy registries
                CodecRegistry.register(instance)
                logger.info(
                    "Registered codec instance: %s.%s.%s (%s)",
                    getattr(instance, "origin", "?"),
                    getattr(instance, "bucket", "?"),
                    getattr(instance, "name", "?"),
                    codec_cls.__name__,
                )
                return
            except Exception as e:
                # Last resort: log and continue without raising at import-time
                logger.warning("Codec registration (instance) failed for %s: %s", codec_cls, e)
                return
        except Exception as e:
            # Registry exists but raised a non-type error; tolerate duplicates/others
            logger.debug("Codec registration (class) non-fatal error for %s: %s", codec_cls, e)
            return
    except Exception:
        # Registry not available; no-op to keep imports safe
        logger.debug("Codec registry not available at import time; skipping registration for %s", codec_cls)
        return


# Build the dual-form codec decorator using the shared factory and core resolver.
codec = make_class_decorator(
    identity_resolver=default_identity_resolver,
    post_register=_post_register_codec,
)

__all__ = ["codec"]
