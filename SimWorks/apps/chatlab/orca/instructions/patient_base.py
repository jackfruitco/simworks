from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import instruction


@instruction(order=50)
class PatientBaseInstruction(BaseInstruction):
    """Base instructions for standardized patient roleplay."""

    instruction = (
        "### General\n"
        "You are a standardized patient role player for medical training.\n"
        "Select a diagnosis and develop a corresponding clinical scenario "
        "script using simple, everyday language that reflects the knowledge "
        "level of an average person.\n"
    )
