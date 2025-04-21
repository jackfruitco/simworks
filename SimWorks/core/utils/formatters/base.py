import decimal
import html
import logging
import os
import uuid
from datetime import datetime

from django.http import HttpResponse

from core.utils.formatters.registry import registry

logger = logging.getLogger(__name__)

class Formatter:
    """
    A flexible data wrapper for rendering output in various formats.

    Wraps data from querysets, lists of dicts, or single dicts and
    serializes them into different textual formats for display, export, or AI use.
    """
    def __init__(self, data):
        self.data = data

    @staticmethod
    def safe_serialize(obj):
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

    def safe_data(self):
        """
        Returns a list of dicts with all values safely serialized.
        Ensures the data is JSON/CSV-safe by applying _safe_serialize and Unicode normalization to every value.
        """
        def decode_unicode_escapes(text):
            try:
                return text.encode('utf-8').decode('unicode_escape')
            except Exception:
                return text

        def clean_string(s):
            if isinstance(s, str):
                return html.unescape(decode_unicode_escapes(s))
            return s

        def _clean(obj):
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_clean(i) for i in obj]
            else:
                return clean_string(obj)

        raw = self.as_serializable()
        row_dicts = []
        for row in raw:
            if isinstance(row, dict):
                cleaned = {k: self.safe_serialize(_clean(v)) for k, v in row.items()}
                row_dicts.append(cleaned)
            else:
                row_dicts.append({"value": self.safe_serialize(_clean(row))})
        return row_dicts

    def as_serializable(self):
        """
        Normalize internal data to a list of dictionaries for processing.
        """
        from collections.abc import Iterable
        if isinstance(self.data, dict):
            return [self.data]
        if isinstance(self.data, Iterable) and not isinstance(self.data, str):
            return list(self.data)
        return [self.data]

    def render(self, format_type: str, **kwargs) -> str:
        """
        Render the wrapped data into the specified format.

        Args:
            format_type (str): One of the registered formatters names or known extensions (e.g., .md, .csv).

        Returns:
            str: The rendered output string.
        """
        format_type = format_type.strip().lower().lstrip(".")
        format_key = registry.extension_map.get(format_type, format_type)

        formatter = registry.get_with_fallback(format_key)
        if not formatter:
            logger.warning(f"[Formatter] Unknown format type requested: '{format_type}'")
            return registry.get_with_fallback("json")(self)

        try:
            return formatter(self, **kwargs)
        except Exception as e:
            logger.error(f"[Formatter] Failed to render '{format_type}': {e}")
            return registry.get_with_fallback("json")(self)

    def save(self, format_type, path: str = None, **kwargs):
        """
        Render the data to a file.

        Args:
            format_type (str): The formatter to use ("json", "csv", etc.).
            path (str, optional): Where to write the file.
            **kwargs: Extra args passed to the formatter (e.g., indent).

        Returns:
            str: The path written to.
        """
        if not path:
            basename = f"formatted_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{format_type}"
            path = os.path.join(os.getcwd(), basename)

        output = self.render(format_type, **kwargs)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(output)
        except IOError as e:
            logger.error(f"[Formatter] Failed to write to {path}: {e}")
            raise

    def download(self, format_type, filename=None, content_type=None, **kwargs):
        """
        Render and return the data as a downloadable HTTP response.

        Args:
            format_type (str): The formatter to use (e.g., 'json', 'md', etc.).
            filename (str, optional): If not given, will be generated.
            content_type (str, optional): MIME type to send. Defaults based on format.
            **kwargs: Additional options passed to the formatter.

        Returns:
            HttpResponse: A response that triggers a browser download.
        """
        output = self.render(format_type, **kwargs)
        format_type = format_type.strip().lower().lstrip(".")
        format_key = registry.extension_map.get(format_type, format_type)

        # Attempt to infer file extension from the format key
        ext = next((k for k, v in registry.extension_map.items() if v == format_key), format_key)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if not filename:
            filename = f"transcript_{timestamp}.{ext}"
        elif not filename.endswith(f".{ext}"):
            filename = f"{filename}.{ext}"

        if not content_type:
            content_type = {
                "json": "application/json",
                "csv": "text/csv",
                "md": "text/markdown",
                "markdown": "text/markdown",
                "txt": "text/plain",
            }.get(ext, "application/octet-stream")

        response = HttpResponse(output, content_type=content_type)
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def pretty_print(self, indent=2, output=None):
        """
        Pretty-print the data as formatted JSON to stdout or optionally save it to a file.

        Args:
            indent (int): Indentation level for pretty-printing.
            output (str, optional): If provided, writes the output to this file path instead of printing.
        """
        if output:
            self.save("json", path=output, indent=indent)
        else:
            print(self.render("json", indent=indent))

    @staticmethod
    def supported_formats():
        """Return a list of all supported formatter types."""
        return registry.available_formats()

    @staticmethod
    def supported_extensions():
        """
        Return a list of supported file extensions mapped to formatters types.
        """
        return list(registry.extension_map.keys())
