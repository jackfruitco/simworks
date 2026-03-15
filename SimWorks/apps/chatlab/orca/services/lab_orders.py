# chatlab/orca/services/lab_orders.py
"""Lab order result generation service for ChatLab."""

from typing import ClassVar

from apps.chatlab.orca.instructions.lab_orders import (
    LabOrderPatientContextInstruction,
    LabOrderResultDetailInstruction,
    LabOrderSchemaContractInstruction,
    LabOrderTestListInstruction,
)
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca


@orca.service
class GenerateLabResults(
    LabOrderPatientContextInstruction,
    LabOrderTestListInstruction,
    LabOrderSchemaContractInstruction,
    LabOrderResultDetailInstruction,
    DjangoBaseService,
):
    """Generate structured lab and radiology results for signed lab orders.

    Accepts a list of ordered test names via context and returns clinically
    plausible results consistent with the patient's presentation.

    Context keys:
        simulation_id (int): The simulation to generate results for.
        orders (list[str]): Ordered test names (e.g. ["CBC", "BMP", "Chest X-Ray"]).
    """

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id", "orders")
    use_native_output = True

    from apps.chatlab.orca.schemas.lab_orders import LabOrderResultsOutputSchema as _Schema

    response_schema = _Schema
