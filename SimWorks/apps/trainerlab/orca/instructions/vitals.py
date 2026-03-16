# trainerlab/orca/instructions/vitals.py

import json

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca

from ..identity_mixins import TrainerlabNamespaceMixin as NsMixin

__all__ = [
    "VitalsProgressionContextInstruction",
    "VitalsProgressionContractInstruction",
    "VitalsProgressionRoleInstruction",
]


@orca.instruction(order=20)
class VitalsProgressionRoleInstruction(NsMixin, BaseInstruction):
    instruction = (
        "You are a clinical vital-signs progression engine for a live medical training scenario. "
        "Your sole task is to update the patient's physiological measurements based on elapsed "
        "scenario time, active conditions, and applied interventions. "
        "Produce medically realistic, internally consistent vital sign ranges. "
        "Do not change conditions or interventions — only update vitals."
    )


@orca.instruction(order=30)
class VitalsProgressionContractInstruction(NsMixin, BaseInstruction):
    instruction = (
        "Return only the structured vitals-progression schema with these top-level fields:\n"
        "- vitals: A list of vital sign updates. Each entry must include:\n"
        "  - vital_type: one of heart_rate, respiratory_rate, spo2, etco2, "
        "blood_glucose, blood_pressure.\n"
        "  - min_value and max_value: realistic physiological range (integers, min <= max).\n"
        "  - lock_value: true if the value should be exact (min used), false for a range.\n"
        "  - trend: one of up, down, stable, variable.\n"
        "  - For blood_pressure: also include min_value_diastolic and max_value_diastolic.\n"
        "- rationale: A brief (1-3 sentence) clinical explanation of why these values changed.\n\n"
        "Every vital sign must appear in the output even if unchanged."
    )


@orca.instruction(order=40)
class VitalsProgressionContextInstruction(NsMixin, BaseInstruction):
    def render_instruction(self) -> str:
        snapshot = json.dumps(self.context.get("current_snapshot", {}), sort_keys=True)
        elapsed = self.context.get("active_elapsed_seconds", 0)
        reasons = json.dumps(self.context.get("runtime_reasons", []), sort_keys=True)
        return (
            "Current patient context:\n"
            f"- Active elapsed seconds: {elapsed}\n"
            f"- Current snapshot JSON: {snapshot}\n"
            f"- Pending runtime reasons: {reasons}\n"
            "Update all six vital sign types to reflect the patient's current physiological state. "
            "Only change values that are clinically justified by the conditions and elapsed time."
        )
