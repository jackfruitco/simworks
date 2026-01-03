"""OpenAI Responses API schema adapters."""

from typing import Any, Dict
from orchestrai.components.schemas.adapters import BaseSchemaAdapter


class OpenaiBaseSchemaAdapter(BaseSchemaAdapter):
    """Base class for OpenAI-specific schema adapters."""
    provider_slug = "openai-prod"


class OpenaiFormatAdapter(OpenaiBaseSchemaAdapter):
    """Adapt generic JSON Schema into OpenAI Responses API format envelope.

    Transforms a validated JSON Schema into the OpenAI-specific structure
    required by the Responses API's text.format parameter.

    Input:  {"type": "object", "properties": {...}}
    Output: {"format": {"type": "json_schema", "name": "response", "schema": {...}}}

    This is a real adaptation - converting from generic JSON Schema to
    provider-specific envelope format.

    Order: 999 (runs last, after any other transformations)
    """
    order = 999

    def adapt(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Wrap schema in OpenAI Responses API format envelope."""
        return {
            "format": {
                "type": "json_schema",
                "name": "response",
                "schema": schema,
            }
        }


# Export for backward compatibility
__all__ = ["OpenaiBaseSchemaAdapter", "OpenaiFormatAdapter"]
