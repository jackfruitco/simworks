# core/utils/formatters/builtins/csv_formatter.py
from core.utils.formatters.registry import register_formatter


@register_formatter("sim_transcript_csv", extension="csv")
def sim_transcript_as_csv(self):
    """
    Render data as CSV text.
    """
    import csv
    import io

    output = io.StringIO()
    output.write("\ufeff")  # Write UTF-8 BOM --> Excel compatability
    writer = csv.DictWriter(output, fieldnames=["timestamp", "sender", "content"])
    writer.writeheader()
    for row in self.safe_data():
        writer.writerow(
            {
                "timestamp": row.get("timestamp", ""),
                "sender": row.get("sender", ""),
                "content": row.get("content", ""),
            }
        )
    return output.getvalue()
