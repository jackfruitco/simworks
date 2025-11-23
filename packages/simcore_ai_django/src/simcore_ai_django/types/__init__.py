# simcore_ai_django/types/__init__.py
"""
This module contains all the types used in the simcore_ai_django package.

Most types are defined in the simcore_ai.types module, but may be extended with django specific types.
"""

from simcore_ai.types import *
from .demote import *
from .django_dtos import *
from .promote import *

__all__ = [
    "StrictBaseModel",
    "Boolish",

    "DjangoDTOBase",

    "DjangoLLMBaseTool",

    "DjangoLLMRequestMessage",
    "DjangoRequest",
    "LLMRole",

    "DjangoLLMResponse",
    "DjangoLLMResponseItem",
    "DjangoLLMUsage",

    "DjangoLLMToolCall",

    "LLMTextPart",
    "LLMImagePart",
    "LLMAudioPart",
    "LLMToolCallPart",
    "LLMToolResultPart",

    "demote_request",
    "demote_response",
    "promote_request",
    "promote_response",
]
