# simcore_ai_django/types/__init__.py
"""
This module contains all the types used in the simcore_ai_django package.

Most types are defined in the simcore_ai.types module, but may be extended with django specific types.
"""

from simcore_ai.types import (
    StrictBaseModel,
    StrictOutputSchema,
    Boolish,
    LLMTextPart,
    LLMImagePart,
    LLMAudioPart,
    LLMToolCallPart,
    LLMToolResultPart,
)
from .demote import demote_request, demote_response
from .django_dtos import (
    DjangoDTOBase,
    DjangoLLMRequestMessage,
    DjangoLLMRequest,
    DjangoLLMResponseItem,
    DjangoLLMUsage,
    DjangoLLMResponse,
    DjangoLLMBaseTool,
    DjangoLLMToolCall,
)
from .promote import promote_request, promote_response
# from simcore_ai_django.services.base import DjangoBaseLLMService

__all__ = [
    "StrictBaseModel",
    "StrictOutputSchema",
    "Boolish",

    "DjangoDTOBase",

    "DjangoLLMBaseTool",
    "DjangoLLMRequestMessage",
    "DjangoLLMRequest",
    "DjangoLLMResponseItem",
    "DjangoLLMUsage",
    "DjangoLLMResponse",
    "DjangoLLMToolCall",
    "DjangoLLMToolSpec",

    "LLMTextPart",
    "LLMImagePart",
    "LLMAudioPart",
    "LLMToolCallPart",
    "LLMToolResultPart",

    "demote_request",
    "demote_response",
    "promote_request",
    "promote_response",
    # "DjangoBaseLLMService",
]
