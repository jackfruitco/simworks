# trainerlab/orca/instructions/runtime.py

import json

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin


@orca.instruction(order=20)
class TrainerRuntimeRoleInstruction(NsMixin, BaseInstruction):
    instruction = (
        "You are the live TrainerLab runtime engine for a medical training scenario. "
        "Update the patient state clinically based on elapsed scenario time, causes, problems, "
        "vitals, and explicitly recorded trainee/instructor/system interventions. Keep changes "
        "internally consistent and prioritize realistic combat and trauma progression. "
        "Never invent or imply that a new intervention was performed. Recommendations are "
        "separate from performed interventions, and problem treatment/control/resolution is "
        "adjudicated by engine rules after explicit interventions."
    )


@orca.instruction(order=30)
class TrainerRuntimeContractInstruction(NsMixin, BaseInstruction):
    instruction = (
        "Return only the structured runtime-turn schema with these top-level fields:\n"
        "- state_changes: Deltas only — new/updated/resolved problems, trending vital ranges, "
        "updated pulse assessments (location + present/description/color/condition/temperature), "
        "and intervention effect records.\n"
        "- snapshot: The COMPLETE current patient state after applying state_changes. "
        "Include all active causes, all active problems, all current recommended interventions, "
        "all current vital ranges, all current pulse assessments (all sites), all active "
        "interventions, and a patient_status summary.\n"
        "- instructor_intent: The AI engine's forward-looking plan for the instructor.\n"
        "- rationale_notes: Brief clinical reasoning strings explaining this turn's decisions.\n\n"
        "state_changes.problems entries (one per change):\n"
        "- action: 'create' | 'update' | 'resolve'\n"
        "- cause_kind: 'injury' | 'illness'\n"
        "- target_problem_id: Problem ID from snapshot.problems[].problem_id — "
        "REQUIRED for 'update' and 'resolve' actions; omit on 'create'.\n"
        "- problem_kind: canonical problem kind/code (required for create/update).\n"
        "- title: problem display label (required for create/update).\n"
        "- march_category: MARCH triage code (M, A, R, C, H1, H2, PC) — required for create/update.\n"
        "- severity: 'low'|'moderate'|'high'|'critical' — required for create/update.\n"
        "- For injury create/update: injury_location (anatomic code), injury_kind (mechanism "
        "code), injury_description (brief text) — all required.\n"
        "- For illness create/update: name (illness name, required), description (optional).\n\n"
        "snapshot.causes entries (OUTPUT):\n"
        "- id, cause_kind, kind/code, title, description, anatomical_location.\n\n"
        "snapshot.problems entries (OUTPUT — full current problem state after applying changes):\n"
        "- problem_id: Problem ID — copy from input context; null for newly created problems.\n"
        "- kind/code/title: canonical problem identity.\n"
        "- status: 'active' | 'treated' | 'controlled' | 'resolved'\n"
        "- march_category: MARCH triage code.\n"
        "- severity: 'low' | 'moderate' | 'high' | 'critical'.\n"
        "- cause_id and cause_kind: explicit linkage back to the owning cause.\n"
        "- description: optional clinical notes.\n"
        "NOTE: The input context snapshot now separates immutable causes from mutable problems. "
        "Read the cause/problem pairing for context. Do not claim a problem is treated, "
        "controlled, or resolved because of an intervention unless that intervention already "
        "exists in the input context and the engine can adjudicate it.\n\n"
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
            "The snapshot includes explicit `causes`, `problems`, `recommended_interventions`, and "
            "`interventions`. Treat `interventions` as the only performed actions. "
            "Only recommend deterioration that is justified by the current causes/problems, elapsed "
            "time, and intervention effectiveness. Instructor intent should help an instructor "
            "anticipate what the engine is likely to do next."
        )
