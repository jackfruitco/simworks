# core/utils/formatters/builtins/openai_prompt.py

from core.utils.formatters.registry import register_formatter

@register_formatter("openai_prompt", extension="txt")
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