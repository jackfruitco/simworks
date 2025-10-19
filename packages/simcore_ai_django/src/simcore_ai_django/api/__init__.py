# simcore_ai_django/api/__init__.py
"""Stable API facade for SimWorks."""

from __future__ import annotations

from .client import *
from .decorators import *
from .mixins import *
from .identity import *
from .tracing import *
from .types import *

__all__ = [
    # decorators
    "prompt_section",
    "prompt_scenario",
    "codec",
    "llm_service",

    # mixins
    "DjangoIdentityMixin",

    # client
    "get_ai_client",
    "get_default_client",
    "call_default",

    # identity
    "derive_django_identity_for_class",
    "get_app_label_for_class",
    "resolve_collision_django",

    # services
    "DjangoBaseLLMService",
    "DjangoExecutableLLMService",

    # tracing
    "service_span_sync",

    # tools
    "DjangoLLMBaseTool",
    "DjangoLLMToolCall",
    # types
    # TODO add types to API
]