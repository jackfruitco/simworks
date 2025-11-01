# chatlab/ai/services/patient.py (v3 services)
from __future__ import annotations

import logging
from typing import Type, Optional, Tuple, List

from chatlab.ai.mixins import ChatlabMixin
from chatlab.models import Message
from core.utils import remove_null_keys
from simcore.ai.mixins import StandardizedPatientMixin
from simcore.models import Simulation
from simcore_ai.types import LLMTextPart, LLMRole
from simcore_ai_django.api.decorators import llm_service
# Django-aware service base and rich DTOs
from simcore_ai_django.api.types import DjangoExecutableLLMService
# PromptKit v3 (used for the image case)
from simcore_ai_django.promptkit import PromptEngine
# Tool DTO (provider-agnostic)
from simcore_ai_django.types import DjangoLLMBaseTool, DjangoLLMRequestMessage

logger = logging.getLogger(__name__)


# ----------------------------- services ------------------------------------------
@llm_service
class GenerateInitialResponse(ChatlabMixin, StandardizedPatientMixin, DjangoExecutableLLMService):
    """Generate the initial patient response.

    Uses Simulation.prompt_instruction/message to construct rich Django request messages
    and validates against the structured output schema.
    """

    # Execution defaults (service-level); None => use settings / hard defaults
    # execution_mode: Optional[str] = "sync"  # "sync" | "async"
    # execution_backend: Optional[str] = "immediate"  # "immediate" | "celery" | "django_tasks"
    # execution_priority: Optional[int] = -100  # -100..100
    # execution_run_after: Optional[float] = None  # seconds; None => now
    # require_enqueue: bool = False # force async if True

    # model: Optional[str] = None  # allow provider default
    # from ..prompts import ChatlabPatientInitialSection
    # prompt_plan = (
    #     ChatlabPatientInitialSection,
    # )

    required_context_keys: tuple[str, ...] = ("simulation_id",)


@llm_service
class GenerateReplyResponse(ChatlabMixin, StandardizedPatientMixin, DjangoExecutableLLMService):
    """Generate a reply to a user message.

    Expects a user message pk (or a resolved Message) and validates against the
    reply structured output schema.
    """

    # Execution defaults (service-level); None => use settings / hard defaults
    # execution_mode: Optional[str] = None  # "sync" | "async"
    # execution_backend: Optional[str] = None  # "immediate" | "celery" | "django_tasks"
    # execution_priority: Optional[int] = None  # -100..100
    # execution_run_after: Optional[float] = None  # seconds; None => now
    # require_enqueue: bool = False  # force async if True

    model: Optional[str] = None

    from chatlab.ai.schemas import PatientReplyOutputSchema as _Schema
    response_format_cls = _Schema

    required_context_keys: tuple[str, ...] = ("simulation_id",)

    # service ctor may receive this
    user_msg_pk: Optional[int] = None

    async def build_messages_and_schema(
            self, *, sim: Simulation, user_msg: Message | None = None
    ) -> Tuple[List[DjangoLLMRequestMessage], Optional[Type[_Schema]]]:
        # Resolve user message if only pk provided
        if user_msg is None and self.user_msg_pk is not None:
            try:
                user_msg = await Message.objects.aget(id=self.user_msg_pk)
            except Message.DoesNotExist:
                logger.warning(
                    "No Message found with pk=%s -- continuing without it", self.user_msg_pk
                )
                user_msg = None

        msgs: List[DjangoLLMRequestMessage] = []
        if user_msg and user_msg.content:
            msgs.append(DjangoLLMRequestMessage(
                role=LLMRole.USER,
                content=[LLMTextPart(text=user_msg.content)])
            )
        return msgs, self.response_format_cls


@llm_service
class GenerateImageResponse(ChatlabMixin, StandardizedPatientMixin, DjangoExecutableLLMService):
    """Generate a patient image via provider tool-call.

    Builds a developer instruction via PromptKit and attaches a normalized image
    generation tool. No structured schema is required by default.
    """

    # Execution defaults (service-level); None => use settings / hard defaults
    execution_mode: Optional[str] = "async"
    # execution_backend: Optional[str] = None
    # execution_priority: Optional[int] = None
    # execution_run_after: Optional[float] = None
    require_enqueue: bool = True

    model: Optional[str] = None

    required_context_keys: tuple[str, ...] = ("simulation_id",)

    # Tool options
    output_format: Optional[str] = None  # e.g., "png" | "jpeg"

    async def build_messages_and_schema(
            self, *, sim: Simulation, user_msg: Message | None = None
    ) -> Tuple[List[DjangoLLMRequestMessage], Optional[Type[None]]]:
        # Use a PromptKit section to generate the instruction for image generation
        from ..prompts import ChatlabImageSection  # local import to avoid cycles
        prompt = await PromptEngine.abuild_from(ChatlabImageSection)
        msgs: List[DjangoLLMRequestMessage] = [
            DjangoLLMRequestMessage(
                role=LLMRole.DEVELOPER,
                content=[LLMTextPart(text=prompt.instruction or "")]
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
