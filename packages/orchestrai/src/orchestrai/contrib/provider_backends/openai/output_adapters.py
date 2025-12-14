# orchestrai/providers/openai/output_adapters.py
from typing import Any, Protocol
from uuid import uuid4

from openai.types.responses.response_output_item import ImageGenerationCall

from orchestrai.types import LLMToolCall
from orchestrai.types.content import BaseToolResultContent

"""
OpenAI-specific output adapters.

These helpers convert backend-native output items into normalized tool call
and tool result DTOs used by the core transport layer.
"""


class ImageGenerationOutputAdapter:
    """Adapt OpenAI image generation outputs into normalized tool results."""

    def adapt(self, item: Any) -> tuple[LLMToolCall, BaseToolResultContent] | None:
        if not isinstance(item, ImageGenerationCall):
            return None

        call_id = getattr(item, "id", None) or str(uuid4())
        b64 = getattr(item, "result", None)
        mime = getattr(item, "mime_type", None) or "image/png"
        if not b64:
            return None

        call = LLMToolCall(call_id=call_id, name="image_generation", arguments={})
        result = BaseToolResultContent(call_id=call_id, mime_type=mime, data_b64=b64)
        return call, result
