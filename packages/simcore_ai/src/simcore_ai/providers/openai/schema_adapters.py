# simcore_ai/providers/openai/schema_adapters.py
from typing import Any, Dict

"""
OpenAI-specific schema adapters.

These helpers are used by provider-aware codecs to adapt JSON Schemas
for the OpenAI Responses API (e.g., flattening oneOf unions).
"""

class FlattenUnions:
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
                    node["description"] = (
                            (node.get("description") or "") +
                            " NOTE: Provider does not support 'oneOf' union types; flattened union. "
                            "Use your discriminator field in prompt."
                    ).strip()
                return node
            if isinstance(node, list):
                return [walk(x) for x in node]
            return node

        return walk(schema)
