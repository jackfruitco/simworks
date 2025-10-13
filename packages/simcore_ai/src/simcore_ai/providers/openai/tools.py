# simcore_ai/providers/openai/tools.py
from __future__ import annotations

from ..base import BaseProvider
from ...types.tools import LLMToolSpec


class OpenAIToolAdapter(BaseProvider.ToolAdapter):
    """Adapter for OpenAI tool/function specs from/to our normalized Tool DTOs."""
    provider = "openai"

    def to_provider(self, tool: "LLMToolSpec") -> dict:  # type: ignore[name-defined]
        """
        Map our provider-agnostic LLMToolSpec to OpenAI Responses API tool spec.
        - image generation: {"type": "image_generation"}
        - function tool: {"type": "function", "function": {"name": ..., "parameters": ...}}
        """
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

    def from_provider(self, raw: dict | object) -> "LLMToolSpec":  # type: ignore[name-defined]
        """
        Best-effort reverse mapping from OpenAI tool spec into our LLMToolSpec.
        """
        from ...types.tools import LLMToolSpec  # local import to avoid cycles
        if isinstance(raw, dict):
            t = raw.get("type")
            if t == "image_generation":
                return LLMToolSpec(name="image_generation", description="OpenAI image generation tool", input_schema={})
            if t == "function":
                fn = raw.get("function") or {}
                return LLMToolSpec(
                    name=fn.get("name") or "tool",
                    description=fn.get("description"),
                    input_schema=fn.get("parameters") or {},
                    strict=bool(fn.get("strict")) if "strict" in fn else None,
                )
        # Fallback: unknown type
        return LLMToolSpec(name=str(getattr(raw, "name", "tool")), input_schema={})
