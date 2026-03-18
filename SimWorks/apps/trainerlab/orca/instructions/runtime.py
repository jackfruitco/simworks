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
        "- state_changes: Deltas only — advisory problem observations, trending vital ranges, "
        "updated pulse assessments, assessment finding updates, recommendation suggestions, "
        "and intervention assessment records.\n"
        "- patient_status: Current clinical summary assessment only. Do not echo the whole "
        "snapshot back.\n"
        "- instructor_intent: The AI engine's forward-looking plan for the instructor.\n"
        "- rationale_notes: Brief clinical reasoning strings explaining this turn's decisions.\n\n"
        "state_changes.problem_observations entries:\n"
        "- observation: 'new_problem' | 'worsening' | 'improving' | 'resolved_candidate' | "
        "'stable'\n"
        "- target_problem_id: required for existing-problem observations.\n"
        "- cause_kind and cause_id: required for new_problem observations.\n"
        "- parent_problem_id: optional for derived secondary problems.\n"
        "- problem_kind/title/description: canonical clinical problem information.\n"
        "- march_category/severity/anatomical_location/laterality: include when known.\n\n"
        "state_changes.finding_updates entries:\n"
        "- action: 'create' | 'update' | 'remove'\n"
        "- target_finding_id: required for update/remove.\n"
        "- target_problem_id: optional but preferred when a finding belongs to a problem.\n"
        "- finding_kind/title/description/status/severity/anatomical_location/laterality.\n\n"
        "state_changes.recommendation_suggestions entries:\n"
        "- intervention_kind/title/target_problem_id are required.\n"
        "- target_cause_ref is optional context only.\n"
        "- rationale/priority/site/warnings/contraindications are advisory suggestions only.\n\n"
        "state_changes.intervention_assessments entries:\n"
        "- intervention_event_id refers to an already-recorded performed intervention.\n"
        "- status/effectiveness/clinical_effect/notes describe the observed effect.\n\n"
        "patient_status fields:\n"
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
            "The snapshot includes explicit `causes`, `problems`, `recommended_interventions`, "
            "`interventions`, `assessment_findings`, `diagnostic_results`, `resources`, and "
            "`disposition`. Treat `interventions` as the only performed actions. Never create or "
            "update causes directly. Recommend observations and suggestions only; the deterministic "
            "engine will decide what actually persists. Never imply that care was performed unless "
            "it already exists in the input context. Instructor intent should help an instructor "
            "anticipate what the engine is likely to do next."
        )
