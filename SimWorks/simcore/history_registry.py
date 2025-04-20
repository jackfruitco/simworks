# simcore/history_registry.py

import json
import csv
import io

_registry = {}
_formatters = {}


def register_history_provider(app_label, func):
    """
    Register a history retrieval function for a specific app.
    Each function must accept a Simulation and return a list of history records (dicts).
    """
    _registry[app_label] = func


def register_formatter(format_name, formatter_func):
    """
    Register a formatter function for a specific format (e.g., json, csv, md).
    """
    _formatters[format_name] = formatter_func


def get_sim_history(simulation, format: str = None):
    """
    Returns a combined list of history records from all registered apps for a given simulation.
    If a format is provided, returns a formatted representation.
    """
    history = []
    for app_label, func in _registry.items():
        try:
            history.extend(func(simulation))
        except Exception as e:
            from django.conf import settings
            if settings.DEBUG:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"[get_sim_history] Failed for {app_label}: {e}")

    if format is None:
        return history

    formatter = _formatters.get(format)
    if not formatter:
        raise ValueError(f"No formatter registered for format '{format}'")
    return formatter(history)


# --- Example Formatters ---

def as_json(history: list) -> str:
    return json.dumps(history, indent=2)


def as_csv(history: list) -> str:
    if not history:
        return ""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=history[0].keys())
    writer.writeheader()
    writer.writerows(history)
    return output.getvalue()


def as_markdown(history: list) -> str:
    if not history:
        return "No history available."

    headers = list(history[0].keys())
    rows = ["| " + " | ".join(headers) + " |"]
    rows.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for record in history:
        row = [str(record.get(header, "")) for header in headers]
        rows.append("| " + " | ".join(row) + " |")

    return "\n".join(rows)


# Register default formatters
register_formatter("json", as_json)
register_formatter("csv", as_csv)
register_formatter("md", as_markdown)