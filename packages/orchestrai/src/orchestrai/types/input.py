# orchestrai/types/input.py
"""
Input-side content types for normalized backend responses.

These classes wrap the base content primitives defined in `content.py`,
assigning request-side `type` discriminators, and
are used by InputItem in `messages.py`.

All input messages ultimately carry `InputContent` instances.
"""
from typing import Literal

from .base import StrictBaseModel
from .content import (
    BaseTextContent,
    BaseImageContent,
    BaseAudioContent,
    BaseFileContent,
    BaseScreenshotContent,
)

__all__ = (
    "InputContent",

    "InputTextContent",
    "InputImageContent",
    "InputAudioContent",
    "InputFileContent",
    "InputScreenshotContent",
)

class InputTextContent(BaseTextContent):
    """Request-side text content (e.g., OpenAI 'input_text')."""
    type: Literal["input_text"] = "input_text"


class InputImageContent(BaseImageContent):
    """Request-side image content."""
    type: Literal["input_image"] = "input_image"


class InputAudioContent(BaseAudioContent):
    """Request-side audio content."""
    type: Literal["input_audio"] = "input_audio"


class InputFileContent(BaseFileContent):
    """Request-side generic file content."""
    type: Literal["input_file"] = "input_file"


class InputScreenshotContent(BaseScreenshotContent):
    """Request-side computer screenshot content."""
    type: Literal["computer_screenshot"] = "computer_screenshot"


InputContent = InputTextContent | InputImageContent | InputAudioContent | InputFileContent | InputScreenshotContent
