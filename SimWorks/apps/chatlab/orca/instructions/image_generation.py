from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import instruction


@instruction(order=50)
class ImageGenerationInstruction(BaseInstruction):
    """Instructions for patient image generation."""

    instruction = (
        "For this response only, generate an image based off the medical "
        "backend's request in the message(s).\n"
        "Images must not be against OpenAI guidelines.\n"
        "The image should be as if taken by the patient with a smartphone. "
        "The image should not show details that would not normally be seen "
        "in an image. Do not overexaggerate the look of a sign or symptom."
    )
