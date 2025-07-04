# SimWorks/simai/prompts/builtins/_lab.py
"""PromptModifiers that modify the Lab modality of a simulation."""
from simai.prompts.registry import register_modifier


@register_modifier("Lab.ChatLab")
def chatlab_modifier(user=None, role=None, **kwargs):
    """Returns string for ChatLab simulation prompt modifier."""
    return """
        Adopt an SMS-like conversational tone from your very first message and
        maintain this informal style consistently throughout the conversation—
        without using slang or clinical language.

        Choose a diagnosis that a non-medical person might realistically text
        about, and avoid conditions that clearly represent immediate
        emergencies (such as massive trauma or a heart attack), which would not
        typically be communicated via text.\n\n
        """


@register_modifier("Lab.VoiceLab")
def voicelab_modifier(user=None, role=None, **kwargs):
    """Returns string for VoiceLab simulation prompt modifier."""
    pass
