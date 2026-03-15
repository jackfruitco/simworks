# trainerlab/orca/instructions/debrief.py

import json

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin


@orca.instruction(order=20)
class TrainerDebriefRoleInstruction(NsMixin, BaseInstruction):
    instruction = (
        "You are an expert medical training debrief facilitator. "
        "Summarize what happened in the scenario, what the trainee did well, what they missed, "
        "and what teaching points the instructor should emphasize."
    )


@orca.instruction(order=30)
class TrainerDebriefContractInstruction(NsMixin, BaseInstruction):
    instruction = (
        "Return only the structured debrief schema. "
        "Keep the feedback instructor-facing, concise, and grounded in the actual scenario events."
    )


@orca.instruction(order=40)
class TrainerDebriefContextInstruction(NsMixin, BaseInstruction):
    def render_instruction(self) -> str:
        final_state = json.dumps(self.context.get("final_state", {}), sort_keys=True)
        timeline = json.dumps(self.context.get("timeline_highlights", []), sort_keys=True)
        notes = json.dumps(self.context.get("notes", []), sort_keys=True)
        commands = json.dumps(self.context.get("command_log", []), sort_keys=True)
        return (
            "Scenario end-state context:\n"
            f"- Final state JSON: {final_state}\n"
            f"- Timeline highlights JSON: {timeline}\n"
            f"- Instructor notes JSON: {notes}\n"
            f"- Command log JSON: {commands}\n"
            "Use this to produce the narrative summary, deterioration timeline, strengths, misses, "
            "and teaching points."
        )
