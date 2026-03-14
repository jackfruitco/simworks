# trainerlab/orca/instructions/runtime.py

import json

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin


@orca.instruction(order=20)
class TrainerRuntimeRoleInstruction(NsMixin, BaseInstruction):
    instruction = (
        "You are the live TrainerLab runtime engine for a medical training scenario. "
        "Update the patient state clinically based on elapsed scenario time, injuries, vitals, "
        "and trainee interventions. Keep changes internally consistent and prioritize realistic "
        "combat and trauma progression."
    )


@orca.instruction(order=30)
class TrainerRuntimeContractInstruction(NsMixin, BaseInstruction):
    instruction = (
        "Return only the structured runtime-turn schema. "
        "Use condition changes for new or evolving injuries/illnesses, vital updates for trending "
        "measurements, intervention effects to explain whether interventions are helping, and "
        "snapshot/instructor_intent to describe the current patient plus what is likely next."
    )


@orca.instruction(order=40)
class TrainerRuntimeContextInstruction(NsMixin, BaseInstruction):
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
