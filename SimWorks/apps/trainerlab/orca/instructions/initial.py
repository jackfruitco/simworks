# trainerlab/orca/instructions/initial.py
"""Dynamic instruction classes for TrainerLab initial scenario service.

Static instructions (TrainerLabMixin, InitialResponseMixin) are defined in
initial.yaml (same directory).
"""

from apps.trainerlab.injury_dictionary import build_injury_codebook_instruction
from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin

__all__ = [
    "InjuryCodebookMixin",
]


@orca.instruction(order=15)
class InjuryCodebookMixin(NsMixin, BaseInstruction):
    group = "initial"

    def render_instruction(self) -> str:
        return build_injury_codebook_instruction()


@orca.instruction(order=5)
class TrainerLabMixin(NsMixin, BaseInstruction):
    group = "initial"
    instruction = (
        "The user is a medical training instruction proctoring a live simulation medical scenario lane for a student. "
        "Assist with generating the patient scenario and provide concise instructor support."
    )


@orca.instruction(order=10)
class InitialResponseMixin(NsMixin, BaseInstruction):
    group = "initial"
    instruction = (
        "Generate a scenario_brief read out loud to the trainee, including scene context and evacuation options. "
        "Then generate initial conditions, initial vitals, and clinically consistent pulse assessments."
    )
