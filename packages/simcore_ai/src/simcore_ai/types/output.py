# simcore_ai/types/output.py
"""
Output-side content types for normalized provider responses.

These classes wrap the base content primitives defined in `content.py`,
assigning response-side `type` discriminators, and
are used by OutputItem in `messages.py`.

All output messages ultimately carry `OutputContent` instances.
"""

from typing import Literal

from .base import StrictBaseModel
from .content import (
    BaseTextContent,
    BaseImageContent,
    BaseAudioContent,
    BaseFileContent,
    BaseScreenshotContent,
    BaseToolCallContent,
    BaseToolResultContent,
)

__all__ = (
    "OutputContent",
    "OutputTextContent",
    "OutputImageContent",
    "OutputAudioContent",
    "OutputFileContent",
    "OutputScreenshotContent",
    "OutputToolCallContent",
    "OutputToolResultContent",
    "OutputJsonContent",
)

#
# ---- Output-side content -----------------------------------------------------
#

class OutputTextContent(BaseTextContent):
    """Assistant text output (OpenAI: `output_text`)."""
    type: Literal["output_text"] = "output_text"


class OutputImageContent(BaseImageContent):
    """Image returned from a provider."""
    type: Literal["output_image"] = "output_image"


class OutputAudioContent(BaseAudioContent):
    """Audio returned from a provider."""
    type: Literal["output_audio"] = "output_audio"


class OutputFileContent(BaseFileContent):
    """Generic file returned from a provider (rare)."""
    type: Literal["output_file"] = "output_file"


class OutputScreenshotContent(BaseScreenshotContent):
    """A screenshot produced by a tool or provider."""
    type: Literal["output_screenshot"] = "output_screenshot"


class OutputToolCallContent(BaseToolCallContent):
    """Tool request emitted by a provider."""
    type: Literal["tool_call"] = "tool_call"


class OutputToolResultContent(BaseToolResultContent):
    """Tool result emitted by a provider."""
    type: Literal["tool_result"] = "tool_result"


class OutputJsonContent(BaseJsonContent):
    type: Literal["output_json"] = "output_json"


#
# ---- Union -------------------------------------------------------------------
#

OutputContent =                 \
    OutputTextContent           \
    | OutputImageContent        \
    | OutputAudioContent        \
    | OutputFileContent         \
    | OutputScreenshotContent   \
    | OutputToolCallContent     \
    | OutputJsonContent         \
    | OutputToolResultContent
