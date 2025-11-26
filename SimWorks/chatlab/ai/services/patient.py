# chatlab/ai/services/patient.py


import logging
from typing import Type, Optional, Tuple, List, ClassVar

from core.utils import remove_null_keys
from simcore_ai_django.api import simcore
from simcore_ai_django.api.types import DjangoBaseService, PromptEngine
from simcore_ai.types.input import InputTextContent
from simcore_ai.types import ContentRole
from simcore_ai_django.types import DjangoLLMBaseTool, DjangoInputItem
from simulation.ai.mixins import StandardizedPatientMixin
from simulation.ai.prompts import PatientNameSection
from simulation.models import Simulation
from ..mixins import ChatlabMixin
from ..prompts.sections import ChatlabPatientInitialSection
from ...models import Message

logger = logging.getLogger(__name__)


# ----------------------------- services ------------------------------------------
@simcore.service
class GenerateInitialResponse(ChatlabMixin, StandardizedPatientMixin, DjangoBaseService):
    """Generate the initial patient response.

    Uses Simulation.prompt_instruction/message to construct rich Django request input
    and validates against the structured output schema.
    """

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)

    # prompt_plan = (
    #     ChatlabPatientInitialSection,
    #     PatientNameSection,
    # )
    prompt_plan = (
        "chatlab.default.base",
        "chatlab.standardized_patient.initial",
        "simcore.standardized_patient.name",
    )

@simcore.service
class GenerateReplyResponse(ChatlabMixin, StandardizedPatientMixin, DjangoBaseService):
    """Generate a reply to a user message.

    Expects a user message pk (or a resolved Message) and validates against the
    reply structured output schema.
    """

    model: Optional[str] = None

    from chatlab.ai.schemas import PatientReplyOutputSchema as _Schema
    response_format_cls = _Schema

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)

    # service ctor may receive this
    user_msg_pk: Optional[int] = None

    async def build_messages_and_schema(
            self, *, sim: Simulation, user_msg: Message | None = None
    ) -> Tuple[List[DjangoInputItem], Optional[Type[_Schema]]]:
        # Resolve user message if only pk provided
        if user_msg is None and self.user_msg_pk is not None:
            try:
                user_msg = await Message.objects.aget(id=self.user_msg_pk)
            except Message.DoesNotExist:
                logger.warning(
                    "No Message found with pk=%s -- continuing without it", self.user_msg_pk
                )
                user_msg = None

        msgs: List[DjangoInputItem] = []
        if user_msg and user_msg.content:
            msgs.append(DjangoInputItem(
                role=ContentRole.USER,
                content=[InputTextContent(text=user_msg.content)])
            )
        return msgs, self.response_format_cls


@simcore.service
class GenerateImageResponse(ChatlabMixin, StandardizedPatientMixin, DjangoBaseService):
    """Generate a patient image via provider tool-call.

    Builds a developer instruction via PromptKit and attaches a normalized image
    generation tool. No structured schema is required by default.
    """

    model: Optional[str] = None

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)

    # Tool options
    output_format: Optional[str] = None  # e.g., "png" | "jpeg"

    async def build_messages_and_schema(
            self, *, sim: Simulation, user_msg: Message | None = None
    ) -> Tuple[List[DjangoInputItem], Optional[Type[None]]]:
        # Use a PromptKit section to generate the instruction for image generation
        from ..prompts import ChatlabImageSection  # local import to avoid cycles
        prompt = await PromptEngine.abuild_from(ChatlabImageSection)
        msgs: List[DjangoInputItem] = [
            DjangoInputItem(
                role=ContentRole.DEVELOPER,
                content=[InputTextContent(text=prompt.instruction or "")]
            )
        ]
        return msgs, None

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
