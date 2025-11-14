# simcore_ai/providers/openai/schema_adapters.py
from typing import Any, Dict

from .base import PROVIDER_NAME
from simcore_ai.components.schemas.compiler import schema_adapter


@schema_adapter(PROVIDER_NAME, order=50)
class FlattenUnions:
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
