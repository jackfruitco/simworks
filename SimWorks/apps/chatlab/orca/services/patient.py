# chatlab/orca/services/patient.py
"""Patient AI services for ChatLab using class-based instructions."""

import logging
from typing import ClassVar

from apps.chatlab.orca.instructions import (
    ImageGenerationInstruction,
    PatientBaseInstruction,
    PatientInitialDetailInstruction,
    PatientNameInstruction,
    PatientRecentScenarioHistoryInstruction,
    PatientReplyDetailInstruction,
    PatientSafetyBoundariesInstruction,
    PatientSchemaContractInstruction,
)
from apps.common.orca.instructions import CharacterConsistencyInstruction
from orchestrai_django.components.services import DjangoBaseService, PreviousResponseMixin
from orchestrai_django.decorators import orca

logger = logging.getLogger(__name__)


@orca.service
class GenerateInitialResponse(
    PatientNameInstruction,
    CharacterConsistencyInstruction,
    PatientSafetyBoundariesInstruction,
    PatientBaseInstruction,
    PatientSchemaContractInstruction,
    PatientRecentScenarioHistoryInstruction,
    PatientInitialDetailInstruction,
    DjangoBaseService,
):
    """Generate the initial patient response."""

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.chatlab.orca.schemas import PatientInitialOutputSchema as _Schema

    response_schema = _Schema


@orca.service
class GenerateReplyResponse(
    PreviousResponseMixin,
    PatientNameInstruction,
    CharacterConsistencyInstruction,
    PatientSafetyBoundariesInstruction,
    PatientBaseInstruction,
    PatientSchemaContractInstruction,
    PatientReplyDetailInstruction,
    DjangoBaseService,
):
    """Generate a reply to a user message."""

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
class GenerateImageResponse(
    ImageGenerationInstruction,
    DjangoBaseService,
):
    """Generate a patient image via Pydantic AI."""

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    # No structured schema - image generation uses tool calling
    response_schema = None
