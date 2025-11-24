# simcore_ai/providers/openai/output_adapters.py
from typing import Any, Protocol
from uuid import uuid4

from openai.types.responses.response_output_item import ImageGenerationCall

from simcore_ai.types import LLMToolCall
from simcore_ai.types.content import ToolResultContent

"""
OpenAI-specific output adapters.

These helpers convert provider-native output items into normalized tool call
and tool result DTOs used by the core transport layer.
"""


class OutputAdapter(Protocol):
    """Protocol for provider-native output adapters.

    Implementations should return a (LLMToolCall, ToolResultContent) tuple
    when they recognize the item, or None otherwise.
    """

    def adapt(self, item: Any) -> tuple[LLMToolCall, ToolResultContent] | None: ...


class ImageGenerationOutputAdapter:
    """Adapt OpenAI image generation outputs into normalized tool results."""

    def adapt(self, item: Any) -> tuple[LLMToolCall, ToolResultContent] | None:
        if not isinstance(item, ImageGenerationCall):
            return None

        call_id = getattr(item, "id", None) or str(uuid4())
        b64 = getattr(item, "result", None)
        mime = getattr(item, "mime_type", None) or "image/png"
        if not b64:
            return None

        call = LLMToolCall(call_id=call_id, name="image_generation", arguments={})
        result = ToolResultContent(call_id=call_id, mime_type=mime, data_b64=b64)
        return call, result
