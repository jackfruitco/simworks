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
        "Return only the structured debrief schema with these fields:\n"
        "- narrative_summary: Required. A concise paragraph describing what happened in the "
        "scenario — the clinical progression, key decision points, and outcome.\n"
        "- strengths: List of specific things the trainee did well, grounded in actual scenario "
        "events. Empty list if none.\n"
        "- misses: List of specific things the trainee missed, did incorrectly, or failed to do "
        "in time. Empty list if none.\n"
        "- deterioration_timeline: List of key clinical events in chronological order. Each item "
        "requires: title (short event label), timestamp_label (human-readable time reference, "
        "e.g. 'T+2:30'), and significance (why this moment mattered clinically or educationally).\n"
        "- teaching_points: List of educational takeaways the instructor should emphasize in "
        "the debrief discussion. Distinct from misses — frame as learning objectives.\n"
        "- overall_assessment: Required. A holistic one-to-two sentence qualitative summary of "
        "the trainee's performance.\n"
        "Keep all feedback instructor-facing, concise, and grounded in the actual scenario events."
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
