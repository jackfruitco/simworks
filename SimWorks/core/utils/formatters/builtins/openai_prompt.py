# core/utils/formatters/builtins/openai_prompt.py
from core.utils.formatters.registry import register_formatter


@register_formatter("openai_prompt", extension="txt")
def as_openai_prompt(self) -> str:
    """
    Render user scenario log as an OpenAI prompt string.
    """
    if not self.data:
        return ""
    return (
        "This user has recently completed scenarios with the following "
        "`(chief complaint, diagnosis)` pairs. Avoid repeating them excessively.\n\n"
        f"{self.render('log_pairs')}\n\n"
    )


@register_formatter("openai_sim_transcript", extension="txt")
def as_openai_sim_transcript(self) -> str:
    """
    Render Simulation History as a plain-text OpenAI transcript string.

    Example output:
        Patient: "I’m not feeling well."
        User: "Can you tell me more?"
        Patient: "Yeah, I have a headache."
    """
    ROLE_LABELS = {"A": "Patient", "U": "User"}

    if not self.data:
        return ""

    def get_role(msg):
        return msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)

    def get_content(msg):
        return (
            msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
        )

    lines = []
    for message in self.data:
        sender = ROLE_LABELS.get(get_role(message), "Unknown")
        content = get_content(message).strip()
        if content:
            lines.append(f'{sender}: "{content}"')

    return "\n".join(lines)
