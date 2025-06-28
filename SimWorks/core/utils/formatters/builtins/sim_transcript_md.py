from datetime import datetime

from core.utils.formatters.registry import register_formatter


@register_formatter("sim_transcript_md", extension="md")
def sim_transcript_as_markdown(self):
    """
    Render Chat History as a Markdown file.
    Each message is shown with the sender's name and a horizontal rule separator.
    """
    if not self.data:
        return ""

    return self.render("sim_transcript_txt")
