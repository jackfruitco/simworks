# simcore_ai_django/api/__init__.py
"""Stable API facade for SimWorks."""



from .registry import *
from .client import *
from .decorators import *
from .identity import *
from .mixins import *
from .tracing import *
from .types import *

__all__ = [
    # registry
    "services", "codecs", "schemas", "prompt_sections", "BaseRegistry", "get_registry_for",

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

    # tracing
    "service_span_sync",

    # tools
    "DjangoLLMBaseTool",
    "DjangoLLMToolCall",

    # types
    # TODO add types to API
]
