# simcore/ai/providers/openai/tools.py
from __future__ import annotations

from typing import Any

from openai.types.responses.tool import ImageGeneration

from ..base import ProviderBase


class OpenAIToolAdapter(ProviderBase.ToolAdapter):
    """Adapter for OpenAI tool/function specs from/to our ToolItem DTOs."""
    provider = "openai"

    def to_provider(self, tool: "ToolItem") -> Any:  # type: ignore[name-defined]
        # Expecting kind=="image_generation" or function-based tools; adapt to OpenAI's tool schema
        # For image generation via Responses API, OpenAI uses `tools=[{"type":"image_generation"}]` variant.
        # If you use function tools, map to {"type":"function", "function": {...}}.
        if tool.kind == "image_generation":
            # Map our DTO to OpenAI ImageGeneration spec
            # `ImageGeneration` pydantic model takes fields like size, background, prompt_bias, etc.
            allowed = getattr(ImageGeneration, "model_fields", {}).keys()
            filtered = {k: v for k, v in (tool.arguments or {}).items() if k in allowed}
            return ImageGeneration(**filtered)
        # default: function tool
        return {
            "type": "function",
            "function": {
                "name": tool.function or "tool",
                "parameters": tool.arguments or {},
            },
        }

    def from_provider(self, raw: Any) -> "ToolItem":  # type: ignore[name-defined]
        from simcore.ai.schemas.types import ToolItem  # local import to avoid cycles
        # OpenAI returns {"type":"function", "function": {...}} or an ImageGeneration model
        if isinstance(raw, ImageGeneration):
            return ToolItem(kind="image_generation", function="generate", arguments=raw.model_dump())
        if isinstance(raw, dict) and raw.get("type") == "function":
            fn = raw.get("function") or {}
            return ToolItem(kind="function", function=fn.get("name"), arguments=fn.get("parameters") or {})
        # Fallback generic
        return ToolItem(kind=str(getattr(raw, "type", "function")), function=getattr(raw, "name", None),
                        arguments=getattr(raw, "parameters", {}) or {})
