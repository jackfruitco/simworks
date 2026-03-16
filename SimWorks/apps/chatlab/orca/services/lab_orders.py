# chatlab/orca/services/lab_orders.py
"""Lab order result generation service for ChatLab."""

from typing import ClassVar

from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca


@orca.service
class GenerateLabResults(DjangoBaseService):
    """Generate structured lab and radiology results for signed lab orders.

    Accepts a list of ordered test names via context and returns clinically
    plausible results consistent with the patient's presentation.

    Context keys:
        simulation_id (int): The simulation to generate results for.
        orders (list[str]): Ordered test names (e.g. ["CBC", "BMP", "Chest X-Ray"]).
    """

    instruction_refs: ClassVar[list[str]] = [
        "chatlab.lab_orders.LabOrderPatientContextInstruction",
        "chatlab.lab_orders.LabOrderTestListInstruction",
        "chatlab.lab_orders.LabOrderSchemaContractInstruction",
        "chatlab.lab_orders.LabOrderResultDetailInstruction",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id", "orders")
    use_native_output = True

    from apps.chatlab.orca.schemas.lab_orders import LabOrderResultsOutputSchema as _Schema

    response_schema = _Schema
