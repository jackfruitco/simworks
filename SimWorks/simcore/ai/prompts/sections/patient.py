# simcore/ai/prompts/sections/patient.py
from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

from simcore.ai.mixins import SimcoreMixin, StandardizedPatientMixin
from simcore.models import Simulation
from simcore_ai_django.api.decorators import prompt_section
from simcore_ai_django.api.types import PromptSection


@prompt_section
@dataclass
class PatientNameSection(PromptSection, SimcoreMixin, StandardizedPatientMixin):
    # name = "name"

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
