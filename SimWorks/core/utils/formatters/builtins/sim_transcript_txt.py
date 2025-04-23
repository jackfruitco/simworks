from datetime import datetime
from core.utils.formatters.registry import register_formatter

@register_formatter("sim_transcript_txt", extension="txt")
def sim_transcript_as_text(self):
    """
    Render Chat History as Plain Text.
    Each message is shown with the sender's name and a horizontal rule separator.
    """
    if not self.data:
        return ""

    messages = self.safe_data()

    lines = []
    for msg in messages:
        sender = msg.get("sender", "System")
        raw_timestamp = msg.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(raw_timestamp)
            # Break apart components to strip leading zeroes manually
            month = dt.strftime("%m").lstrip("0")
            day = dt.strftime("%d").lstrip("0")
            year = dt.strftime("%Y")
            hour = dt.strftime("%I").lstrip("0")  # 12-hour
            minute = dt.strftime("%M")  # Keep leading zero for minute
            ampm = dt.strftime("%p")
            timestamp = f"{month}/{day}/{year} {hour}:{minute} {ampm}"
        except Exception:
            timestamp = raw_timestamp  # fallback

        content = msg.get("content", "")
        lines.append(f"##### {sender} – {timestamp}\n{content}")

    return "\n\n---\n\n".join(lines)