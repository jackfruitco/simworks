# simcore/ai/prompts/sections/standardized_patient.py
from django.core.exceptions import ObjectDoesNotExist

from simcore.models import Simulation
from simcore_ai_django.promptkit import PromptSection, prompt


@prompt
class PatientNameSection(PromptSection):
    name = "patient_name"
    category = "patient"

    # weight = 100
    # tags =

    async def render_instruction(self, **ctx) -> str | None:
        options_ = ("simulation", "sim_id", "sim_pk", "sim_obk")

        for opt in options_:
            if simulation_ := opt in ctx:
                break
        else:
            raise ValueError(f"Missing required context variable(s): {options_}")

        if not isinstance(simulation_, Simulation):
            try:
                simulation_ = await Simulation.objects.aget(pk=simulation_)
            except (TypeError, ValueError, ObjectDoesNotExist):
                raise ValueError(f"Cannot resolve Simulation with input {simulation_!r}")

        return (
            f"As standardized patient, your name is {simulation_.sim_patient_full_name}."
        )