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
    "InitialResponseMixin",
    "InjuryCodebookMixin",
    "TrainerLabMixin",
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


@orca.instruction(order=5)
class TrainerLabMixin(NsMixin, BaseInstruction):
    group = "initial"
    instruction = (
        "The user is a medical training instruction proctoring a live simulation medical scenario lane for a "
        "student. Assist with generating the patient scenario and provide concise instructor support."
    )


@orca.instruction(order=10)
class InitialResponseMixin(NsMixin, BaseInstruction):
    group = "initial"
    instruction = (
        "First, generate a scenario_brief that the instructor will read out loud to the trainee "
        "before the simulation begins. The brief should include a concise spoken read-aloud "
        "opening plus structured context about the environment, approximate location, scene or "
        "enemy threat if applicable, evacuation options if applicable, expected evacuation time "
        "if applicable, and any other special considerations that matter to the lane.\n\n"
        "Then, generate explicit `causes`, `problems`, and `recommended_interventions`.\n"
        "- Causes are immutable source records only. Use `cause_kind='injury'` or "
        "`cause_kind='illness'` and do not embed problem lifecycle fields on causes.\n"
        "- Problems are the actionable clinical entities. Every problem must reference exactly "
        "one cause via `cause_ref`.\n"
        "- One cause may create multiple problems.\n"
        "- Recommended interventions are suggestions only. They must target a problem, not a cause.\n"
        "- Every `problems[*].recommendation_refs` entry must exactly equal a "
        "`recommended_interventions[*].temp_id` value.\n"
        "- Do not use recommendation titles, labels, or descriptive aliases inside "
        "`recommendation_refs`.\n"
        "- If useful, also generate structured `assessment_findings`, `diagnostic_results`, "
        "`resources`, and `disposition` to support the simulation state.\n"
        "- Findings should describe what an examiner can detect now.\n"
        "- Diagnostic results should represent pending/available/reviewed tests or labs.\n"
        "- Resources should capture meaningful supply constraints for care.\n"
        "- Disposition should capture evacuation or transport readiness constraints.\n"
        "- `performed_interventions` must be omitted or an empty list unless trusted system "
        "context explicitly says a real intervention was already performed.\n"
        "- Never state or imply that an intervention was performed unless the input explicitly "
        "provides that action.\n"
        "- Never mark a problem treated, controlled, or resolved because of an intervention "
        "unless that intervention was explicitly provided and will be adjudicated by engine rules.\n\n"
        "Prefer medically meaningful decomposition.\n"
        "Good examples:\n"
        "- Cause: GSW left thigh\n"
        "- Problem: Massive hemorrhage from left thigh\n"
        "- Recommended intervention: Tourniquet to left thigh\n"
        "Bad examples:\n"
        "- GSW treated with tourniquet\n"
        "- Bleeding controlled\n"
        "- Needle decompression performed\n\n"
        "Then, provide an initial set of vital sign measurements that match the patient's "
        "status clinically, including: "
        "heart rate, "
        "blood pressure, "
        "respiratory rate, "
        "SPO2, "
        "ETCO2, "
        "blood glucose level.\n\n"
        "Then, provide pulse assessments for all clinically relevant anatomic sites. "
        "For each site, include both sides (left and right) for: radial, femoral, carotid, pedal. "
        "For each assessment provide:\n"
        "- present: whether the pulse is palpable (bool)\n"
        "- description: pulse quality — one of: strong, bounding, weak, absent, thready\n"
        "- color_normal: whether skin color is normal (bool)\n"
        "- color_description: one of: pink, pale, mottled, cyanotic, flushed\n"
        "- condition_normal: whether skin condition/moisture is normal (bool)\n"
        "- condition_description: one of: dry, moist, diaphoretic, clammy\n"
        "- temperature_normal: whether skin temperature is normal (bool)\n"
        "- temperature_description: one of: warm, cool, cold, hot\n"
        "Pulse assessments must be clinically consistent with the patient's injuries and vitals."
    )
