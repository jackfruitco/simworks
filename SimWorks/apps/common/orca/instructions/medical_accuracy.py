from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import instruction


@instruction(order=15)
class MedicalAccuracyInstruction(BaseInstruction):
    """Medical accuracy enforcement for clinical simulation services."""

    instruction = (
        "### Medical Accuracy\n"
        "- Ensure all medical information is clinically accurate and realistic.\n"
        "- Do not provide medical advice outside the simulation context.\n"
        "- Do not attempt to diagnose or treat the user directly.\n"
        "- Maintain medically plausible scenarios and patient presentations."
    )
