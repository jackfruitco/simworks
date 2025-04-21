# core/utils/formatters.py

import logging
logger = logging.getLogger(__name__)

_formatter_registry = {}

def register_formatter(name):
    def decorator(func):
        _formatter_registry[name] = func
        return func
    return decorator

class Formatter:
    def __init__(self, data):
        self.data = data

    @register_formatter("json")
    def as_json(self, indent=None):
        import json
        return json.dumps(self._as_serializable(), indent=indent)

    @register_formatter("log_pairs")
    def as_log_pairs(self):
        pairs = []
        for entry in self._as_serializable():
            cc = entry.get("chief_complaint")
            dx = entry.get("diagnosis")
            if cc and dx:
                pairs.append(f'("{cc}", "{dx}")')
        return "[" + ", ".join(pairs) + "]"

    @register_formatter("openai_prompt")
    def as_openai_prompt(self):
        if not self.data:
            return ""
        return (
            "This user has recently completed scenarios with the following "
            "'chief complaint: diagnosis' pairs. Avoid repeating them excessively.\n\n"
            f"{self.as_log_pairs()}"
        )

    @register_formatter("csv")
    def as_csv(self):
        import csv
        import io

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["id", "start_timestamp", "diagnosis", "chief_complaint"])
        writer.writeheader()
        for row in self._as_serializable():
            writer.writerow({
                "id": row.get("id", ""),
                "start_timestamp": row.get("start_timestamp", ""),
                "diagnosis": row.get("diagnosis", ""),
                "chief_complaint": row.get("chief_complaint", ""),
            })
        return output.getvalue()

    @register_formatter("markdown")
    def as_markdown(self):
        if not self.data:
            return ""
        rows = self._as_serializable()
        header = "| ID | Timestamp | Diagnosis | Chief Complaint |\n|----|------------|-----------|------------------|"
        lines = [
            f"| {r.get('id', '')} | {r.get('start_timestamp', '')} | {r.get('diagnosis', '')} | {r.get('chief_complaint', '')} |"
            for r in rows
        ]
        return "\n".join([header] + lines)

    def _as_serializable(self):
        from collections.abc import Iterable
        if isinstance(self.data, dict):
            return [self.data]
        if isinstance(self.data, Iterable) and not isinstance(self.data, str):
            return list(self.data)
        return [self.data]

    def render(self, format_type: str) -> str:
        formatter = _formatter_registry.get(format_type)
        if not formatter:
            logger.warning(f"[Formatter] Unknown format type requested: '{format_type}'")
            return self.as_json(indent=2)

        try:
            return formatter(self)
        except Exception as e:
            logger.error(f"[Formatter] Failed to render '{format_type}': {e}")
            return self.as_json(indent=2)

    def supported_formats(self):
        return list(_formatter_registry.keys())