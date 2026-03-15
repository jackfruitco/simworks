"""Instruction classes for lab order result generation services."""

from django.core.exceptions import ObjectDoesNotExist

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=0)
class LabOrderPatientContextInstruction(BaseInstruction):
    async def render_instruction(self) -> str:
        from apps.simcore.models import Simulation

        simulation_id = self.context.get("simulation_id")
        if not simulation_id:
            return "You are generating lab results for a patient in a clinical simulation."

        try:
            simulation = await Simulation.objects.aget(pk=simulation_id)
        except (TypeError, ValueError, ObjectDoesNotExist):
            return "You are generating lab results for a patient in a clinical simulation."

        parts = [
            "### Patient Context",
            f"Patient: {simulation.sim_patient_full_name}",
        ]
        if simulation.chief_complaint:
            parts.append(f"Chief complaint: {simulation.chief_complaint}")
        if simulation.diagnosis:
            parts.append(f"Working/known diagnosis: {simulation.diagnosis}")
        parts.append(
            "Generate results that are clinically plausible and consistent with this patient presentation."
        )
        return "\n".join(parts)


@orca.instruction(order=10)
class LabOrderTestListInstruction(BaseInstruction):
    async def render_instruction(self) -> str:
        orders: list[str] = self.context.get("orders") or []
        if not orders:
            return ""

        order_lines = "\n".join(f"  - {order}" for order in orders)
        return (
            "### Ordered Tests\n"
            "Return exactly one result item per ordered test below. "
            "Do not add unrequested tests. Do not omit any ordered test.\n"
            f"{order_lines}\n"
            "Use the test name as the `key` field (lowercase, underscored, e.g. 'cbc_wbc').\n"
            "Group related tests using a consistent `panel_name` where applicable."
        )


@orca.instruction(order=20)
class LabOrderSchemaContractInstruction(BaseInstruction):
    instruction = (
        "### Schema Contract\n"
        "- Return `results` as a list of items. Each item must be either:\n"
        "  - `{'kind': 'lab_result', 'key': ..., 'value': ..., 'panel_name': ..., "
        "'result_unit': ..., 'reference_range_low': ..., 'reference_range_high': ..., "
        "'result_flag': 'normal'|'abnormal', 'result_comment': ...}`\n"
        "  - `{'kind': 'rad_result', 'key': ..., 'value': ..., 'result_flag': 'normal'|'abnormal'|'critical'}`\n"
        "- Use `kind='lab_result'` for blood/urine/culture panels and similar numeric tests.\n"
        "- Use `kind='rad_result'` for imaging studies (X-ray, CT, MRI, ultrasound, ECG).\n"
        "- Always include `llm_conditions_check` as concise key/value compliance checks.\n"
        "- Do not include patient-facing messages — this schema has no `messages` field.\n"
    )


@orca.instruction(order=30)
class LabOrderResultDetailInstruction(BaseInstruction):
    instruction = (
        "### Result Generation Guidance\n"
        "- Generate results that are clinically plausible for the patient's presentation.\n"
        "- Abnormal results should be consistent with the likely diagnosis.\n"
        "- Normal results should be realistic for the patient's age and demographics.\n"
        "- Include reference ranges and units for all numeric lab results.\n"
        "- For radiology, provide a brief but specific impression (1-3 sentences).\n"
        "- Set `result_flag` to 'abnormal' only when the result is clinically significant.\n"
        "- Add a `result_comment` for critical or clinically important findings.\n"
    )
