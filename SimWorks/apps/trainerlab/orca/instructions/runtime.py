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
        "and intervention effect records.\n"
        "- snapshot: The COMPLETE current patient state after applying state_changes. "
        "Include all active conditions, all current vital ranges, all active interventions, "
        "and a patient_status summary.\n"
        "- instructor_intent: The AI engine's forward-looking plan for the instructor.\n"
        "- rationale_notes: Brief clinical reasoning strings explaining this turn's decisions.\n\n"
        "state_changes.conditions entries (one per change):\n"
        "- action: 'create' | 'update' | 'resolve'\n"
        "- condition_kind: 'injury' | 'illness'\n"
        "- target_event_id: Problem ID from snapshot.conditions[].domain_event_id — "
        "REQUIRED for 'update' and 'resolve' actions; omit on 'create'.\n"
        "- march_category: MARCH triage code (M, A, R, C, H1, H2, PC) — required for "
        "injury and illness create/update.\n"
        "- For injury create/update: injury_location (anatomic code), injury_kind (mechanism "
        "code), injury_description (brief text) — all required.\n"
        "- For illness create/update: name (illness name, required), description (optional), "
        "severity ('low'|'moderate'|'high'|'critical', required).\n\n"
        "snapshot.conditions entries (OUTPUT — full current condition state after applying changes):\n"
        "- domain_event_id: Problem ID — copy from input context; null for newly created conditions.\n"
        "- kind: 'injury' | 'illness' | 'other'\n"
        "- label: display name (injury_description for injuries, illness name for illnesses).\n"
        "- status: 'active' | 'resolved' | 'worsening' | 'improving' | 'stable'\n"
        "- march_category: MARCH triage code.\n"
        "- severity: 'low' | 'moderate' | 'high' | 'critical'.\n"
        "- injury_location, injury_kind: include for injury kind.\n"
        "- description: optional clinical notes.\n"
        "NOTE: The input context snapshot also includes control_state, is_treated, "
        "is_resolved — read these for situational awareness but do NOT include them in your "
        "output snapshot (they are managed by the instructor, not the AI engine).\n\n"
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
