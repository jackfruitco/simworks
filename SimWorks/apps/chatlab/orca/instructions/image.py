"""Instruction classes for image generation.

Static instructions are defined in image.yaml (same directory).
"""

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=50)
class ImageGenerationInstruction(BaseInstruction):
    namespace = "chatlab"
    group = "image"
    instruction = (
        "For this response only, generate an image based off the medical backend's request in the message(s).\n"
        "Images must not violate OpenAI guidelines.\n"
        "The image should look like a patient smartphone photo and should not exaggerate signs or symptoms.\n\n"
        "### Response Schema\n"
        "- This service does not use a structured JSON response schema.\n"
        "- Return only the image-generation response expected by the model/tooling layer.\n"
        "- Do not emit extra JSON wrapper keys."
    )
