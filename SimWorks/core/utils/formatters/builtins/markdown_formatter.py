# core/utils/formatters/builtins/markdown_formatter.py

from core.utils.formatters.registry import register_formatter

@register_formatter("markdown")
def as_markdown(self):
    """
    Render data as a Markdown table.
    """
    if not self.data:
        return ""
    rows = self.safe_data()
    header = "| ID | Timestamp | Diagnosis | Chief Complaint |\n|----|------------|-----------|------------------|"
    lines = [
        f"| {r.get('id', '')} | {r.get('start_timestamp', '')} | {r.get('diagnosis', '')} | {r.get('chief_complaint', '')} |"
        for r in rows
    ]
    return "\n".join([header] + lines)