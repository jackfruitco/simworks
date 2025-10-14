# simcore_ai/providers/openai/tools.py
from __future__ import annotations

from ...tracing import service_span_sync
from ..base import BaseProvider
from ...types.tools import BaseLLMTool


class OpenAIToolAdapter(BaseProvider.ToolAdapter):
    """Adapter for OpenAI tool/function specs from/to our normalized Tool DTOs."""
    provider = "openai"

    def to_provider(self, tool: "BaseLLMTool") -> dict:  # type: ignore[name-defined]
        with service_span_sync(
            "ai.tools.adapt",
            attributes={"ai.provider_name": self.provider, "ai.tool": tool.name},
        ):
            if tool.name == "image_generation":
                return {"type": "image_generation"}
            # Default: function-style tool with JSON Schema parameters
            return {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema or {},
                    # OpenAI 'strict' is optional; include only if set
                    **({"strict": True} if tool.strict else {}),
                },
            }

    def from_provider(self, raw: dict | object) -> "BaseLLMTool":  # type: ignore[name-defined]
        from ...types.tools import BaseLLMTool  # local import to avoid cycles
        with service_span_sync(
            "ai.tools.reverse_adapt",
            attributes={"ai.provider_name": self.provider},
        ):
            if isinstance(raw, dict):
                t = raw.get("type")
                if t == "image_generation":
                    return BaseLLMTool(name="image_generation", description="OpenAI image generation tool", input_schema={})
                if t == "function":
                    fn = raw.get("function") or {}
                    return BaseLLMTool(
                        name=fn.get("name") or "tool",
                        description=fn.get("description"),
                        input_schema=fn.get("parameters") or {},
                        strict=bool(fn.get("strict")) if "strict" in fn else None,
                    )
            # Fallback: unknown type
            return BaseLLMTool(name=str(getattr(raw, "name", "tool")), input_schema={})
