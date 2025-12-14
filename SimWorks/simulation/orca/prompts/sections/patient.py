# simcore/ai/prompts/sections/patient.py
from dataclasses import dataclass

from django.core.exceptions import ObjectDoesNotExist

from orchestrai_django.components.promptkit import PromptSection
from orchestrai_django.decorators import prompt_section
from simulation.orca.mixins import SimcoreMixin, StandardizedPatientMixin
from simulation.models import Simulation


@prompt_section
@dataclass
class PatientNameSection(SimcoreMixin, StandardizedPatientMixin, PromptSection):
    # name = "name"

    weight = 100
    # tags =

    async def render_instruction(self, **ctx) -> str | None:
        options_ = ("simulation_id", "simulation", "sim_id", "sim_pk", "sim_obj")

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
