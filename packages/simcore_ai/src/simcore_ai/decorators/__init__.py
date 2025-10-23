# simcore_ai/decorators/__init__.py
"""Decorator facade (lazy imports to avoid cycles).

This package exposes the base registration decorator and *optionally* the
domain-specific decorator classes/instances via **lazy** attribute access.
We avoid importing domain modules (services, codecs, promptkit, schemas)
at import time to prevent circular imports during early Django startup.

Usage (unchanged for callers):
    from simcore_ai.decorators import BaseRegistrationDecorator
    # Optional (resolved lazily on first access):
    from simcore_ai.decorators import ServiceRegistrationDecorator
    from simcore_ai.decorators import CodecDecorator
    from simcore_ai.decorators import PromptSectionDecorator
    from simcore_ai.decorators import ResponseSchemaDecorator
    # Instances (also lazy):
    from simcore_ai.decorators import service, codec, prompt_section, response_schema
"""
from __future__ import annotations

from typing import Any
from typing import TYPE_CHECKING
if TYPE_CHECKING:  # static analyzers only; avoids runtime import cycles
    from simcore_ai.services.decorators import (ServiceRegistrationDecorator as ServiceRegistrationDecorator,
                                                llm_service as llm_service)
    from simcore_ai.codecs.decorators import (CodecRegistrationDecorator as CodecDecorator,
                                              codec as codec)
    from simcore_ai.promptkit.decorators import (PromptSectionRegistrationDecorator as PromptSectionDecorator,
                                                 prompt_section as prompt_section)
    from simcore_ai.schemas.decorators import (SchemaRegistrationDecorator as ResponseSchemaDecorator,
                                               schema as response_schema)

# Import-safe: the base class does not depend on domain modules.
from .registration import BaseRegistrationDecorator

__all__ = [
    "BaseRegistrationDecorator",
    # Domain classes (lazy)
    "ServiceRegistrationDecorator",
    "CodecDecorator",
    "PromptSectionDecorator",
    "ResponseSchemaDecorator",
    # Ready-to-use instances (lazy)
    "llm_service",
    "codec",
    "prompt_section",
    "response_schema",
]

# Map attribute names to (module, attr) for lazy import
_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    # classes
    "ServiceRegistrationDecorator": ("simcore_ai.services.decorators", "ServiceRegistrationDecorator"),
    "CodecDecorator": ("simcore_ai.codecs.decorators", "CodecDecorator"),
    "PromptSectionDecorator": ("simcore_ai.promptkit.decorators", "PromptSectionDecorator"),
    "ResponseSchemaDecorator": ("simcore_ai.schemas.decorators", "ResponseSchemaDecorator"),
    # instances
    "service": ("simcore_ai.services.decorators", "service"),
    "codec": ("simcore_ai.codecs.decorators", "codec"),
    "prompt_section": ("simcore_ai.promptkit.decorators", "prompt_section"),
    "response_schema": ("simcore_ai.schemas.decorators", "response_schema"),
}


def __getattr__(name: str) -> Any:  # PEP 562
    target = _LAZY_ATTRS.get(name)
    if not target:
        raise AttributeError(name)
    mod_name, attr_name = target
    import importlib

    mod = importlib.import_module(mod_name)
    value = getattr(mod, attr_name)
    globals()[name] = value  # cache for subsequent lookups
    return value
