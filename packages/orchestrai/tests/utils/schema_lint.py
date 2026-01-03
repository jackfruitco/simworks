"""Schema lint helpers for OpenAI strict structured outputs."""
from __future__ import annotations

from typing import Any


def find_open_objects(schema: dict[str, Any]) -> list[str]:
    """Return JSON-pointer-ish paths to object nodes that are not closed.

    An object is considered open when ``additionalProperties`` is either missing,
    truthy, or a schema instead of the literal ``False`` required by OpenAI strict
    structured outputs.
    """
    open_paths: list[str] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, (dict, list)):
            return

        if isinstance(node, dict):
            if node.get("type") == "object":
                if node.get("additionalProperties") is not False:
                    open_paths.append(path or "$")

                for prop_name, prop_schema in (node.get("properties") or {}).items():
                    walk(prop_schema, f"{path}/properties/{prop_name}" if path else prop_name)

            if "items" in node:
                walk(node["items"], f"{path}/items" if path else "items")

            for keyword in ("allOf", "anyOf", "oneOf"):
                for idx, subschema in enumerate(node.get(keyword) or []):
                    walk(subschema, f"{path}/{keyword}/{idx}" if path else f"{keyword}/{idx}")

            for defs_key in ("$defs", "definitions"):
                for name, subschema in (node.get(defs_key) or {}).items():
                    walk(subschema, f"{path}/{defs_key}/{name}" if path else f"{defs_key}/{name}")

        else:
            for idx, item in enumerate(node):
                walk(item, f"{path}/{idx}" if path else str(idx))

    walk(schema, "$")
    return open_paths
