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
        "Return only the structured runtime-turn schema with these top-level fields:\n"
        "- state_changes: Deltas only — new/updated/resolved conditions, trending vital ranges, "
        "updated pulse assessments (location + present/description/color/condition/temperature), "
        "and intervention effect records.\n"
        "- snapshot: The COMPLETE current patient state after applying state_changes. "
        "Include all active conditions, all current vital ranges, all current pulse assessments "
        "(all sites), all active interventions, and a patient_status summary.\n"
        "- instructor_intent: The AI engine's forward-looking plan for the instructor.\n"
        "- rationale_notes: Brief clinical reasoning strings explaining this turn's decisions.\n\n"
        "snapshot.patient_status fields:\n"
        "- avpu: Consciousness level — one of 'Alert', 'Voice', 'Pain', 'Unresponsive'.\n"
        "- respiratory_distress: true if the patient is in active respiratory distress.\n"
        "- hemodynamic_instability: true if BP/HR indicate shock or instability.\n"
        "- impending_pneumothorax: true if tension pneumothorax is developing but not yet present.\n"
        "- tension_pneumothorax: true if tension pneumothorax is fully present.\n"
        "- narrative: One or two sentence clinical summary of the patient's current status.\n"
        "- teaching_flags: List of notable teaching points the instructor should be aware of "
        "right now (empty list if none).\n\n"
        "instructor_intent fields:\n"
        "- summary: One sentence describing what the engine is likely to do next.\n"
        "- rationale: Clinical reasoning explaining why that change is coming.\n"
        "- trigger: The specific condition, elapsed time, or intervention outcome that will "
        "cause the next change.\n"
        "- eta_seconds: Estimated seconds until the next notable change (null if unknown).\n"
        "- confidence: Float 0.0-1.0 reflecting certainty about the next change.\n"
        "- upcoming_changes: Short list of specific changes expected in the next 1-2 turns.\n"
        "- monitoring_focus: Fields or signs the instructor should watch closely right now."
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
