# trainerlab/orca/instructions/runtime.py
"""Dynamic instruction classes for TrainerLab runtime turn service.

Static instructions (TrainerRuntimeRoleInstruction, TrainerRuntimeContractInstruction)
are defined in runtime.yaml (same directory).
"""

import json

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin


@orca.instruction(order=40)
class TrainerRuntimeContextInstruction(NsMixin, BaseInstruction):
    group = "runtime"

    def render_instruction(self) -> str:
        snapshot = json.dumps(self.context.get("current_snapshot", {}), sort_keys=True)
        reasons = json.dumps(self.context.get("runtime_reasons", []), sort_keys=True)
        elapsed = self.context.get("active_elapsed_seconds", 0)
        return (
            "Current runtime context:\n"
            f"- Active elapsed seconds: {elapsed}\n"
            f"- Current snapshot JSON: {snapshot}\n"
            f"- Pending runtime reasons JSON: {reasons}\n"
            "Only recommend deterioration that is justified by the current injuries, elapsed time, "
            "and intervention effectiveness. Instructor intent should help an instructor anticipate "
            "what the engine is likely to do next."
        )


@orca.instruction(order=20)
class TrainerRuntimeRoleInstruction(NsMixin, BaseInstruction):
    group = "runtime"
    instruction = (
        "You are the live TrainerLab runtime engine for a medical training scenario. "
        "Update patient state clinically based on elapsed time, injuries, vitals, and trainee interventions."
    )


@orca.instruction(order=30)
class TrainerRuntimeContractInstruction(NsMixin, BaseInstruction):
    group = "runtime"
    instruction = (
        "Return only the structured runtime-turn schema with top-level fields: "
        "state_changes, snapshot, instructor_intent, rationale_notes."
    )
