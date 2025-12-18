# packages/orchestrai/src/orchestrai/providers/openai/tools.py


from orchestrai.tracing import service_span_sync, flatten_context as _flatten_context
from orchestrai.components.providerkit.provider import BaseProvider
from orchestrai.types.tools import BaseLLMTool


class OpenAIToolAdapter(BaseProvider.ToolAdapter):
    """Adapter for OpenAI tool/function specs from/to our normalized Tool DTOs."""
    provider = "openai"

    def to_provider(self, tool: "BaseLLMTool") -> dict:  # type: ignore[name-defined]
        """
        Convert a normalized tool into an OpenAI Responses API tool spec.

        Notes
        -----
        - 'image_generation' is represented as a simple type discriminator.
        - Function-style tools include a JSON Schema `parameters` object.
        - We include `strict: True` only when requested (truthy), to avoid
          sending the field spuriously to providers that treat absence
          differently from falsey.
        """
        ctx = getattr(tool, "context", {}) or {}
        with service_span_sync(
                "orchestrai.tools.adapt",
                attributes={
                    "orchestrai.provider_name": self.provider,
                    "orchestrai.tool": tool.name,
                    "orchestrai.tool.has_params": bool(getattr(tool, "input_schema", None)),
                    "orchestrai.tool.strict": bool(getattr(tool, "strict", False)),
                    **_flatten_context(ctx),
                },
        ):
            if tool.name == "image_generation":
                return {"type": "image_generation"}

            # Default: function-style tool with JSON Schema parameters
            fn = {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.input_schema or {},
            }
            # OpenAI 'strict' is optional; include only if explicitly True
            if getattr(tool, "strict", False):
                fn["strict"] = True  # type: ignore[index]

            return {
                "type": "function",
                "function": fn,  # type: ignore[arg-type]
            }

    def from_provider(self, raw: dict | object) -> "BaseLLMTool":  # type: ignore[name-defined]
        """
        Convert an OpenAI Responses API tool spec back into a normalized tool.
        """
        from ...types.tools import BaseLLMTool  # local import to avoid cycles
        with service_span_sync(
                "orchestrai.tools.reverse_adapt",
                attributes={"orchestrai.provider_name": self.provider},
        ):
            if isinstance(raw, dict):
                t = raw.get("type")
                if t == "image_generation":
                    return BaseLLMTool(
                        name="image_generation",
                        description="OpenAI image generation tool",
                        input_schema={},
                    )
                if t == "function":
                    fn = raw.get("function") or {}
                    return BaseLLMTool(
                        name=fn.get("name") or "tool",
                        description=fn.get("description"),
                        input_schema=fn.get("parameters") or {},
                        # Preserve explicit strict only if present and truthy; otherwise None
                        strict=True if fn.get("strict") else None,
                    )

            # Fallback: unknown type → best-effort normalization
            return BaseLLMTool(
                name=str(getattr(raw, "name", "tool")),
                input_schema={},
            )
