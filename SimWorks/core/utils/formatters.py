"""
Formatter class for serializing and rendering data into various formats.
Supports JSON, CSV, Markdown, OpenAI prompt-style logs, and custom formats.
Automatically handles serialization of complex Python and Django types.
"""

import decimal
import uuid
import logging

from django.db.models import QuerySet

logger = logging.getLogger(__name__)

_formatter_registry = {}

def register_formatter(name):
    """
    Decorator to register a formatter method under a given name.

    Args:
        name (str): The name used to call the formatter via `render`.

    Returns:
        Callable: The wrapped formatter method.
    """
    def decorator(func):
        _formatter_registry[name] = func
        return func
    return decorator

class Formatter:
    """
    A flexible data wrapper for rendering output in various formats.

    Wraps data from querysets, lists of dicts, or single dicts and
    serializes them into different textual formats for display, export, or AI use.
    """
    def __init__(self, data):
        self.data = data

    def _safe_serialize(self, obj):
        """
        Safely serialize individual values to ensure compatibility with text-based formats.
        Handles common types like datetime, Decimal, and UUID.
        """
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        if isinstance(obj, decimal.Decimal):
            return str(obj)
        if isinstance(obj, uuid.UUID):
            return str(obj)
        return str(obj)

    def _safe_data(self):
        """
        Returns a list of dicts with all values safely serialized.
        Ensures the data is JSON/CSV-safe by applying _safe_serialize to every value.
        """
        raw = self._as_serializable()
        return [{k: self._safe_serialize(v) for k, v in row.items()} for row in raw]

    @register_formatter("json")
    def as_json(self, indent=None):
        """
        Render data as a JSON string.
        """
        import json
        return json.dumps(self._safe_data(), indent=indent, sort_keys=True)

    @register_formatter("log_pairs")
    def as_log_pairs(self):
        """
        Render data as a simplified log-style tuple list.
        """
        pairs = []
        for entry in self._as_serializable():
            cc = entry.get("chief_complaint")
            dx = entry.get("diagnosis")
            if cc and dx:
                pairs.append(f'("{cc}", "{dx}")')
        return "[" + ", ".join(pairs) + "]"

    @register_formatter("openai_prompt")
    def as_openai_prompt(self):
        """
        Render user scenario log as an OpenAI prompt string.
        """
        if not self.data:
            return ""
        return (
            "This user has recently completed scenarios with the following "
            "'chief complaint: diagnosis' pairs. Avoid repeating them excessively.\n\n"
            f"{self.as_log_pairs()}"
        )

    @register_formatter("csv")
    def as_csv(self):
        """
        Render data as CSV text.
        """
        import csv
        import io

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["id", "start_timestamp", "diagnosis", "chief_complaint"])
        writer.writeheader()
        for row in self._safe_data():
            writer.writerow({
                "id": row.get("id", ""),
                "start_timestamp": row.get("start_timestamp", ""),
                "diagnosis": row.get("diagnosis", ""),
                "chief_complaint": row.get("chief_complaint", ""),
            })
        return output.getvalue()

    @register_formatter("markdown")
    def as_markdown(self):
        """
        Render data as a Markdown table.
        """
        if not self.data:
            return ""
        rows = self._safe_data()
        header = "| ID | Timestamp | Diagnosis | Chief Complaint |\n|----|------------|-----------|------------------|"
        lines = [
            f"| {r.get('id', '')} | {r.get('start_timestamp', '')} | {r.get('diagnosis', '')} | {r.get('chief_complaint', '')} |"
            for r in rows
        ]
        return "\n".join([header] + lines)

    def _as_serializable(self):
        """
        Normalize internal data to a list of dictionaries for processing.
        """
        from collections.abc import Iterable
        if isinstance(self.data, dict):
            return [self.data]
        if isinstance(self.data, Iterable) and not isinstance(self.data, str):
            return list(self.data)
        return [self.data]

    def render(self, format_type: str) -> str:
        """
        Render the wrapped data into the specified format.

        Args:
            format_type (str): One of the registered formatter names.

        Returns:
            str: The rendered output string.
        """
        formatter = _formatter_registry.get(format_type)  # Retrieve the formatter from the registry
        if not formatter:
            logger.warning(f"[Formatter] Unknown format type requested: '{format_type}'")
            return self.as_json(indent=2)

        try:
            return formatter(self)  # Call the formatter function
        except Exception as e:
            logger.error(f"[Formatter] Failed to render '{format_type}': {e}")
            return self.as_json(indent=2)

    def pretty_print(self):
        """
        Pretty-print the data to stdout as formatted JSON.
        """
        print(self.as_json(indent=2))

    def supported_formats(self):
        """
        Return a list of all supported formatter types.
        """
        return list(_formatter_registry.keys())
