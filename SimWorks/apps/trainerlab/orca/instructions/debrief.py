# trainerlab/orca/instructions/debrief.py
"""Dynamic instruction classes for TrainerLab debrief service.

Static instructions (TrainerDebriefRoleInstruction, TrainerDebriefContractInstruction)
are defined in debrief.yaml (same directory).
"""

import json

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin


@orca.instruction(order=40)
class TrainerDebriefContextInstruction(NsMixin, BaseInstruction):
    group = "debrief"

    def render_instruction(self) -> str:
        evidence = json.dumps(self.context.get("evidence", []), sort_keys=True)
        return (
            f"Clinical evidence JSON: {evidence}\n"
            f"Omitted physiology records: {self.context.get('evidence_omitted_count', 0)}"
        )
