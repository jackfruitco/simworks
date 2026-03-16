"""Dynamic instruction classes for lab order result generation services.

Static instructions are defined in lab_orders.yaml (same directory).
"""

from django.core.exceptions import ObjectDoesNotExist

from orchestrai.instructions import BaseInstruction
from orchestrai_django.decorators import orca


@orca.instruction(order=0)
class LabOrderPatientContextInstruction(BaseInstruction):
    namespace = "chatlab"
    group = "lab_orders"

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
    namespace = "chatlab"
    group = "lab_orders"

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
