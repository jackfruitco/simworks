# orchestrai/types/messages.py
"""
Data models used for message content handling in the AI module.

This module contains classes that define the structure of input and output messages,
utility models for tracking usage statistics, and tools configuration for processing
tasks in the AI module.

The classes in this module ensure strict type validation using Pydantic and support
dynamic addition of fields for extensibility.
"""
from typing import Dict

from pydantic import Field

from .base import StrictBaseModel
from .content import ContentRole
from .input import InputContent
from .output import OutputContent
from .meta import HasItemMeta


class InputItem(StrictBaseModel):
    """Single input message with a role and one or more content parts."""
    role: ContentRole
    content: list[InputContent]


class OutputItem(HasItemMeta):
    """Single output message with a role and one or more content parts."""
    role: ContentRole
    content: list[OutputContent]


class UsageContent(StrictBaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_tokens: int = 0
    total_tokens: int = 0

    # allow unknown fields from the backend
    model_config = {
        **StrictBaseModel.model_config,
        "extra": "allow",
    }


class ToolItem(StrictBaseModel):
    kind: str  # e.g., "image_generation"
    function: str | None = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
