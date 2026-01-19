# chatlab/ai/services/patient.py
"""
Patient AI Services for ChatLab.

WORKFLOW DIAGRAM
================

    GenerateInitialResponse / GenerateReplyResponse
      -> build request (prompt_plan, response_schema)
      -> provider backend call (openai.py)
      -> post_process (metadata population, codec decode)
      -> coerce via codec.adecode() -> model_validate()
      -> store Response to ServiceCallRecord.result (JSON)
      -> [async] drain worker calls persistence handler
      -> persistence handler: ensure_idempotent() -> model_validate() -> ORM creates
      -> return Response (contains structured_data as Pydantic model)

COERCION BOUNDARY
=================
Provider response -> Codec.adecode() -> schema.model_validate() -> strict Pydantic model

PERSISTENCE CONTRACT
====================
- Persistence handlers receive: Response with structured_data (dict from JSON)
- Must re-validate: schema.model_validate(response.structured_data)
- Creates: Message rows, SimulationMetadata rows
- Idempotency: PersistedChunk with (call_id, schema_identity) unique constraint
"""

import logging
from typing import Type, Optional, Tuple, List, ClassVar

from core.utils import remove_null_keys
from orchestrai_django.components.promptkit import PromptEngine
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import service
from orchestrai.types.input import InputTextContent
from orchestrai.types import ContentRole
from orchestrai_django.types import DjangoLLMBaseTool, DjangoInputItem
from simulation.orca.mixins import StandardizedPatientMixin
from simulation.orca.prompts import PatientNameSection
from simulation.models import Simulation
from ..mixins import ChatlabMixin
from ..prompts.sections import ChatlabPatientInitialSection
from ...models import Message

logger = logging.getLogger(__name__)


# ----------------------------- services ------------------------------------------
@service
class GenerateInitialResponse(ChatlabMixin, StandardizedPatientMixin, DjangoBaseService):
    """Generate the initial patient response.

    Uses Simulation.prompt_instruction/message to construct rich Django request input
    and validates against the structured output schema.
    """

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)

    from chatlab.orca.schemas import PatientInitialOutputSchema as _Schema
    response_schema = _Schema

    prompt_plan = (
        "prompt-sections.chatlab.default.base",
        "prompt-sections.chatlab.standardized_patient.initial",
        "prompt-sections.simcore.standardized_patient.name",
    )

@service
class GenerateReplyResponse(ChatlabMixin, StandardizedPatientMixin, DjangoBaseService):
    """Generate a reply to a user message.

    Expects a user message pk (or a resolved Message) and validates against the
    reply structured output schema.
    """

    model: Optional[str] = None

    from chatlab.orca.schemas import PatientReplyOutputSchema as _Schema
    response_schema = _Schema

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)

    # service ctor may receive this
    user_msg_pk: Optional[int] = None

    prompt_plan = (
        "prompt-sections.chatlab.standardized_patient.reply",
    )


@service
class GenerateImageResponse(ChatlabMixin, StandardizedPatientMixin, DjangoBaseService):
    """Generate a patient image via backend tool-call.

    Builds a developer instruction via PromptKit and attaches a normalized image
    generation tool. No structured schema is required by default.
    """

    model: Optional[str] = None

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)

    # Tool options
    output_format: Optional[str] = None  # e.g., "png" | "jpeg"

    prompt_plan = (
        "prompt-sections.chatlab.standardized_patient.image",
    )

    def build_tools(self) -> list[DjangoLLMBaseTool]:
        args = remove_null_keys({
            "output_format": self.output_format,
        })
        return [
            DjangoLLMBaseTool(
                name="image_generation",
                description="Generate an image from the prompt",
                input_schema={
                    "type": "object",
                    "properties": {"output_format": {"type": "string"}},
                    "required": [],
                },
                arguments=args,
            )
        ]
