# trainerlab/orca/instructions/initial.py

from apps.trainerlab.injury_dictionary import build_injury_codebook_instruction
from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin

__all__ = [
    "InitialResponseMixin",
    "InjuryCodebookMixin",
    "TrainerLabMixin",
]


@orca.instruction(order=5)
class TrainerLabMixin(NsMixin, BaseInstruction):
    instruction = (
        "The user is a medical training instruction proctoring a live, simulation medical "
        "scenario lane for a student. "
        "Your primary role is to assist with generating the patient scenario for the lane, "
        "which will be displayed on a screen to the instructor to guide the student through. "
        "Your secondary role is to track the student's progress, logging key events, and "
        "generating a summary and feedback as needed. "
        "Your secondary role is to provide feedback and guidance to the instructor, ensuring that "
        "the student is engaged and learning effectively. Your goal is to support "
        "the user in providing high-quality medical training scenarios."
    )


@orca.instruction(order=10)
class InitialResponseMixin(NsMixin, BaseInstruction):
    instruction = (
        "First, generate a scenario_brief that the instructor will read out loud to the trainee "
        "before the simulation begins. The brief should include a concise spoken read-aloud "
        "opening plus structured context about the environment, approximate location, scene or "
        "enemy threat if applicable, evacuation options if applicable, expected evacuation time "
        "if applicable, and any other special considerations that matter to the lane.\n\n"
        "Then, generate the initial scenario by providing one or more conditions. "
        "Each condition must include march_category (MARCH triage code) and "
        "severity ('low'|'moderate'|'high'|'critical').\n"
        "- For an injury: also provide injury_location (anatomic code), "
        "injury_kind (mechanism code), and injury_description (brief text).\n"
        "- For an illness: also provide name (illness name) and description (optional).\n\n"
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


@orca.instruction(order=15)
class InjuryCodebookMixin(NsMixin, BaseInstruction):
    def render_instruction(self) -> str:
        return build_injury_codebook_instruction()
