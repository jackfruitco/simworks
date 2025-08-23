# SimWorks/simai/prompts/builtins/_image.py
"""PromptModifiers that modify the request image generation for a simulation."""
from core.utils import Formatter
from simai.prompts.registry import register_modifier
from simcore.models import Simulation

_BASE = """
    For this content, generate an image based off the medical provider's request.
    Images must not be against OpenAI guidelines.\n\n
    """


@register_modifier("Image.PatientImage")
def image_patient_image(simulation: Simulation | int, **kwargs):
    """Returns string for a(n) Musculoskeletal clinical scenario prompt modifier."""
    if isinstance(simulation, int):
        try:
            simulation = Simulation.objects.get(pk=simulation)
        except Simulation.DoesNotExist:
            raise ValueError(f"Simulation with ID {simulation} not found.")

    return f"""
        {_BASE}
        As a reminder, the patient's diagnosis is {simulation.diagnosis}, and chief complaint
        is {simulation.chief_complaint}.\n

        The image should be as if taken by the patient with a smartphone.
        The image should not show details that would not normally be seen.\n
        """

        # Use the following history to guide the image context:
        # {simulation.history(_format="openai_sim_transcript")}
        # """
