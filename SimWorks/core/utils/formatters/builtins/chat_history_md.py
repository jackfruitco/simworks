# core/utils/formatters/builtins/markdown_formatter.py

from core.utils.formatters.registry import register_formatter

@register_formatter("chat_history_md")
def chat_history_as_markdown(self):
    """
    Render Chat History as a Markdown file.
    Each message is shown with the sender's name and a horizontal rule separator.
    """
    if not self.data:
        return ""

    transcript = self.safe_data()

    message = [
        f"##### {getattr(msg, 'sender', 'Unknown')} – {getattr(msg, 'timestamp', '')}\n\n{msg.content}"
        for msg in transcript
    ]
    return "\n---\n".join(message)