# simcore_ai/providers/openai/schema_adapters.py
"""
OpenAI-specific schema adapters.

These helpers are used by provider-aware codecs to adapt JSON Schemas
for the OpenAI Responses API (e.g., flattening oneOf unions).
"""
from typing import Any, Dict

from ...components.schemas.adapters import BaseSchemaAdapter


class OpenaiBaseSchemaAdapter(BaseSchemaAdapter):
    """Base class for OpenAI-specific schema adapters."""
    provider_slug = "openai-prod"


class OpenaiWrapper(OpenaiBaseSchemaAdapter):
    """OpenAI-specific wrapper for JSON Schemas."""
    order = 999                # run last

    def adapt(self, target_: Dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "schema": target_,
            }
        }


class FlattenUnions(OpenaiBaseSchemaAdapter):
    """Flatten oneOf unions into a single object schema.

    This is an OpenAI-specific workaround for providers that do not support
    JSON Schema `oneOf` unions. Codecs for OpenAI JSON output should call
    this adapter as part of their schema pipeline.
    """

    def adapt(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        def walk(node: Any) -> Any:
            if isinstance(node, dict):
                # first, recurse into children
                for k, v in list(node.items()):
                    node[k] = walk(v)
                # then, flatten oneOf unions on object-like nodes
                one = node.get("oneOf")
                if isinstance(one, list):
                    merged_props: Dict[str, Any] = {}
                    for variant in one:
                        if isinstance(variant, dict):
                            merged_props.update(variant.get("properties", {}))
                    node.pop("oneOf", None)
                    node["type"] = "object"
                    node.setdefault("properties", {}).update(merged_props)
                    node.setdefault("required", [])
                    description = (node.get("description") or "").strip()
                    note = (
                        "Provider does not support 'oneOf' union types; flattened union. "
                        "Use a discriminator field in the prompt."
                    )
                    node["description"] = f"{description} NOTE: {note}".strip()
                return node
            if isinstance(node, list):
                return [walk(x) for x in node]
            return node

        return walk(schema)
