# simcore_ai_django/api/__init__.py
"""Stable API facade for SimWorks."""

from __future__ import annotations

from simcore_ai.registry.singletons import (
    services as services,
    codecs as codecs,
    schemas as schemas,
    prompt_sections as prompt_sections,
)
from .client import *
from .decorators import *
from .identity import *
from .mixins import *
from .tracing import *
from .types import *

__all__ = [
    # registry
    "services", "codecs", "schemas", "prompt_sections",

    # decorators
    "ai_prompt_section", "ai_codec", "ai_service", "ai_schema",  # "prompt_scenario",

    # identity
    "Identity", "DjangoIdentityMixin", "DjangoIdentityResolver",

    # client
    "get_ai_client",
    "get_default_client",
    "call_default",

    # services
    "DjangoBaseService",
    "DjangoExecutableLLMService",

    # tracing
    "service_span_sync",

    # tools
    "DjangoLLMBaseTool",
    "DjangoLLMToolCall",

    # types
    # TODO add types to API
]
