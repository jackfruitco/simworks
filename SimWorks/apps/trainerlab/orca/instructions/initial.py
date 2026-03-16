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
    def render_instruction(self) -> str:
        return build_injury_codebook_instruction()
