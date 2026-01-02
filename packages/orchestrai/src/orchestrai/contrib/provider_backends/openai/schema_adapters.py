# orchestrai/contrib/provider_backends/openai/schema_adapters.py
"""OpenAI-specific schema adapters.

Schema adapters transform JSON schemas to accommodate OpenAI Responses API requirements:

1. **FlattenUnions** (order=0): Flattens JSON Schema `oneOf` unions into single objects
   because OpenAI doesn't support union types.

2. **OpenaiWrapper** (order=999): Wraps the schema in OpenAI's required format:
   `{"type": "json_schema", "json_schema": {"name": "response", "schema": {...}}}`

Adapters are applied in order (low to high) to build the final schema.
"""
from typing import Any, Dict

from orchestrai.components.schemas.adapters import BaseSchemaAdapter


class OpenaiBaseSchemaAdapter(BaseSchemaAdapter):
    """Base class for OpenAI-specific schema adapters."""
    provider_slug = "openai-prod"


class FlattenUnions(OpenaiBaseSchemaAdapter):
    """Flatten oneOf unions into a single object schema.

    OpenAI's Responses API does not support JSON Schema `oneOf` unions.
    This adapter walks the schema tree and flattens any `oneOf` constructs
    by merging all variant properties into a single object type.

    **Important**: The prompt must use a discriminator field to guide the model
    when multiple variants exist, since the schema no longer enforces exclusivity.

    **Order**: 0 (runs first, before wrapper)
    """
    order = 0  # Run before wrapper

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


class OpenaiWrapper(OpenaiBaseSchemaAdapter):
    """Wrap JSON schema in OpenAI Responses API format.

    OpenAI requires schemas to be wrapped in a specific envelope:
    ```json
    {
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "schema": {...}
        }
    }
    ```

    This adapter applies that wrapper after all other transformations.

    **Order**: 999 (runs last, after all transformations)
    """
    order = 999  # Run last

    def adapt(self, target_: Dict[str, Any]) -> dict[str, Any]:
        """Wrap the schema in OpenAI's required envelope."""
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "schema": target_,
            }
        }
