# core/utils/formatters/builtins/csv_formatter.py
from core.utils.formatters.registry import register_formatter


@register_formatter("csv")
def as_csv(self):
    """
    Render data as CSV text.
    """
    import csv
    import io

    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=["id", "start_timestamp", "diagnosis", "chief_complaint"]
    )
    writer.writeheader()
    for row in self.safe_data():
        writer.writerow(
            {
                "id": row.get("id", ""),
                "start_timestamp": row.get("start_timestamp", ""),
                "diagnosis": row.get("diagnosis", ""),
                "chief_complaint": row.get("chief_complaint", ""),
            }
        )
    return output.getvalue()
