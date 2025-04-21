# core/utils/formatters/builtins/json_formatter.py

import json
from core.utils.formatters.registry import register_formatter

@register_formatter("json")
def as_json(formatter, indent=None):
    """
    Render data as a JSON string.

    Args:
        formatter (Formatter): The Formatter instance containing the data.
        indent (int, optional): Optional indentation level for pretty-printing.

    Returns:
        str: Serialized JSON string of the safe data.
    """
    return json.dumps(formatter.safe_data(), indent=indent, sort_keys=True)