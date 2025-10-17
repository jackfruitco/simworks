# chatlab/ai/services/patient_responses.py (v3 services)
from __future__ import annotations

import logging
from typing import Type, Optional, Tuple, List

from chatlab.models import Message
from core.utils import remove_null_keys
from simcore.models import Simulation
# PromptKit v3 (used for the image case)
from simcore_ai.promptkit import PromptEngine
from simcore_ai.services.decorators import llm_service
# Tool DTO (provider-agnostic)
from simcore_ai.types import BaseLLMTool
# Django-aware service base and rich DTOs
from simcore_ai_django.services.base import DjangoExecutableLLMService
from simcore_ai_django.types import DjangoLLMRequestMessage

logger = logging.getLogger(__name__)


# ----------------------------- services ------------------------------------------
@llm_service(namespace="chatlab", bucket="patient")
class GenerateInitialResponse(DjangoExecutableLLMService):
    """Generate the initial patient response.

    Uses Simulation.prompt_instruction/message to construct rich Django request messages
    and validates against the structured output schema.
    """

    # Execution defaults (service-level); None => use settings / hard defaults
    execution_mode: Optional[str] = None  # "sync" | "async"
    execution_backend: Optional[str] = None  # "immediate" | "celery" | "django_tasks"
    execution_priority: Optional[int] = None  # -100..100
    execution_run_after: Optional[float] = None  # seconds; None => now
    require_enqueue: bool = False  # force async if True

    model: Optional[str] = None  # allow provider default

    # Structured output schema
    from chatlab.ai.schemas import PatientInitialOutputSchema as _Schema
    response_format_cls = _Schema

    async def build_messages_and_schema(
            self, *, sim: Simulation, user_msg: Message | None = None
    ) -> Tuple[List[DjangoLLMRequestMessage], Optional[Type[_Schema]]]:
        msgs: List[DjangoLLMRequestMessage] = []
        if getattr(sim, "prompt_instruction", None):
            msgs.append(
                DjangoLLMRequestMessage(role="developer", content=sim.prompt_instruction)
            )
        if getattr(sim, "prompt_message", None):
            msgs.append(
                DjangoLLMRequestMessage(role="user", content=sim.prompt_message)
            )
        return msgs, self.response_format_cls


@llm_service(namespace="chatlab", bucket="patient")
class GenerateReplyResponse(DjangoExecutableLLMService):
    """Generate a reply to a user message.

    Expects a user message pk (or a resolved Message) and validates against the
    reply structured output schema.
    """

    # Execution defaults (service-level); None => use settings / hard defaults
    execution_mode: Optional[str] = None  # "sync" | "async"
    execution_backend: Optional[str] = None  # "immediate" | "celery" | "django_tasks"
    execution_priority: Optional[int] = None  # -100..100
    execution_run_after: Optional[float] = None  # seconds; None => now
    require_enqueue: bool = False  # force async if True

    model: Optional[str] = None

    from chatlab.ai.schemas import PatientReplyOutputSchema as _Schema
    response_format_cls = _Schema

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
            msgs.append(DjangoLLMRequestMessage(role="user", content=user_msg.content))
        return msgs, self.response_format_cls


@llm_service(namespace="chatlab", bucket="patient")
class GenerateImageResponse(DjangoExecutableLLMService):
    """Generate a patient image via provider tool-call.

    Builds a developer instruction via PromptKit and attaches a normalized image
    generation tool. No structured schema is required by default.
    """

    # Execution defaults (service-level); None => use settings / hard defaults
    execution_mode: Optional[str] = None
    execution_backend: Optional[str] = None
    execution_priority: Optional[int] = None
    execution_run_after: Optional[float] = None
    require_enqueue: bool = True

    model: Optional[str] = None

    # Tool options
    output_format: Optional[str] = None  # e.g., "png" | "jpeg"

    async def build_messages_and_schema(
            self, *, sim: Simulation, user_msg: Message | None = None
    ) -> Tuple[List[DjangoLLMRequestMessage], Optional[Type[None]]]:
        # Use a PromptKit section to generate the instruction for image generation
        from ..prompts import ImageSection  # local import to avoid cycles
        prompt = await PromptEngine.abuild_from(ImageSection)
        msgs: List[DjangoLLMRequestMessage] = [
            DjangoLLMRequestMessage(role="developer", content=prompt.instruction or "")
        ]
        return msgs, None

    def build_tools(self) -> list[BaseLLMTool]:
        args = remove_null_keys({
            "output_format": self.output_format,
        })
        return [
            BaseLLMTool(
                type="image_generation",
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
