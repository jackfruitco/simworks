from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import instruction


@instruction(order=50)
class PatientReplyDetailInstruction(BaseInstruction):
    """Instructions for generating patient reply responses."""

    instruction = (
        "Continue the conversation in character as the patient. "
        "Respond naturally to what the user says. "
        "Maintain the informal SMS style from the initial message. "
        "Mark 'image_requested': true if an image is requested, otherwise false. "
        "Include llm_conditions_check with workflow flags as needed.\n\n"
        "### Schema Requirements\n"
        "Each message item MUST include all required fields: role, content, and item_meta.\n"
        "- role: 'patient' for patient messages\n"
        "- content: array of content blocks (at least one text block)\n"
        "- item_meta: array of metadata key-value pairs (use empty array [] if none)"
    )
