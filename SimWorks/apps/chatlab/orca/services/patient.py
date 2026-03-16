# chatlab/orca/services/patient.py
"""Patient AI services for ChatLab using class-based instructions."""

import logging
from typing import ClassVar

from orchestrai_django.components.services import DjangoBaseService, PreviousResponseMixin
from orchestrai_django.decorators import orca

logger = logging.getLogger(__name__)


@orca.service
class GenerateInitialResponse(DjangoBaseService):
    """Generate the initial patient response."""

    instruction_refs: ClassVar[list[str]] = [
        "chatlab.patient.PatientNameInstruction",
        "common.shared.CharacterConsistencyInstruction",
        "chatlab.patient.PatientSafetyBoundariesInstruction",
        "chatlab.patient.PatientConversationBehaviorInstruction",
        "chatlab.patient.PatientSchemaContractInstruction",
        "chatlab.patient.PatientRecentScenarioHistoryInstruction",
        "chatlab.patient.PatientInitialDetailInstruction",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.chatlab.orca.schemas import PatientInitialOutputSchema as _Schema

    response_schema = _Schema


@orca.service
class GenerateReplyResponse(PreviousResponseMixin, DjangoBaseService):
    """Generate a reply to a user message."""

    instruction_refs: ClassVar[list[str]] = [
        "chatlab.patient.PatientNameInstruction",
        "common.shared.CharacterConsistencyInstruction",
        "chatlab.patient.PatientSafetyBoundariesInstruction",
        "chatlab.patient.PatientConversationBehaviorInstruction",
        "chatlab.patient.PatientSchemaContractInstruction",
        "chatlab.patient.PatientReplyDetailInstruction",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.chatlab.orca.schemas import PatientReplyOutputSchema as _Schema

    response_schema = _Schema

    async def _aprepare_context(self) -> None:
        """Populate user_message for reply runs using stored user message ID."""
        if hasattr(super(), "_aprepare_context"):
            await super()._aprepare_context()

        if self.context.get("user_message") is not None:
            return

        user_msg_id = self.context.get("user_msg") or self.context.get("user_msg_id")
        if not user_msg_id:
            return

        try:
            from apps.chatlab.models import Message

            msg = await Message.objects.aget(pk=user_msg_id)
        except Exception as exc:
            logger.warning("Unable to load user message %s: %s", user_msg_id, exc)
            return

        self.context["user_message"] = msg.content


@orca.service
class GenerateImageResponse(DjangoBaseService):
    """Generate a patient image via Pydantic AI."""

    instruction_refs: ClassVar[list[str]] = [
        "chatlab.image.ImageGenerationInstruction",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    # No structured schema - image generation uses tool calling
    response_schema = None
