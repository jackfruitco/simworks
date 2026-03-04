from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import instruction


@instruction(order=0)
class FeedbackContinuationInstruction(BaseInstruction):
    """Instructions for feedback continuation responses."""

    instruction = (
        "Continue providing feedback on the student's performance. "
        "Address any specific questions or areas they want to discuss. "
        "Maintain the same educational tone and provide constructive guidance."
    )
