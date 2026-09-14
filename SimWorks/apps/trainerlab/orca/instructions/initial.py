# trainerlab/orca/instructions/initial.py
"""Dynamic instruction classes for TrainerLab initial scenario service.

Static instructions (TrainerLabMixin, InitialResponseMixin) are defined in
initial.yaml (same directory).
"""

from apps.trainerlab.cause_dictionary import build_cause_dictionary_instruction
from apps.trainerlab.diagnostic_dictionary import build_diagnostic_dictionary_instruction
from apps.trainerlab.finding_dictionary import build_finding_dictionary_instruction
from apps.trainerlab.injury_dictionary import build_injury_codebook_instruction
from apps.trainerlab.intervention_dictionary import list_intervention_definitions
from apps.trainerlab.problem_dictionary import build_problem_dictionary_instruction
from apps.trainerlab.recommendations import build_recommendation_compatibility_instruction
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
        interventions = ", ".join(
            f"{definition.type_code}={definition.label}"
            for definition in list_intervention_definitions()
        )
        return (
            build_cause_dictionary_instruction()
            + build_injury_codebook_instruction()
            + build_problem_dictionary_instruction()
            + build_finding_dictionary_instruction()
            + build_diagnostic_dictionary_instruction()
            + build_recommendation_compatibility_instruction()
            + "### Intervention Dictionary\n"
            + "- Use canonical intervention kinds from this list when possible.\n"
            + f"- Intervention kinds: {interventions}\n"
        )
