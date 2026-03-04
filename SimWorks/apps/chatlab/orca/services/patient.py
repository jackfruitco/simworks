# chatlab/orca/services/patient.py
"""
Patient AI Services for ChatLab using Pydantic AI.

Services compose instructions via MRO inheritance from BaseInstruction classes.
Pydantic AI handles execution and validation.
"""

import logging
from typing import ClassVar

from apps.chatlab.orca.instructions import (
    ImageGenerationInstruction,
    PatientBaseInstruction,
    PatientInitialDetailInstruction,
    PatientNameInstruction,
    PatientReplyContextInstruction,
    PatientReplyDetailInstruction,
)
from apps.common.orca.instructions import (
    CharacterConsistencyInstruction,
    MedicalAccuracyInstruction,
    SMSStyleInstruction,
)
from orchestrai_django.components.services import DjangoBaseService, PreviousResponseMixin
from orchestrai_django.decorators import service

logger = logging.getLogger(__name__)


@service
class GenerateInitialResponse(
    PatientNameInstruction,              # order=0  - dynamic patient name
    CharacterConsistencyInstruction,     # order=10 - character roleplay consistency
    MedicalAccuracyInstruction,          # order=15 - clinical accuracy enforcement
    SMSStyleInstruction,                 # order=20 - informal SMS communication style
    PatientBaseInstruction,              # order=50 - base standardized patient roleplay
    PatientInitialDetailInstruction,     # order=90 - detailed initial response instructions
    DjangoBaseService,
):
    """Generate the initial patient response.

    Instructions are composed from the class hierarchy via MRO.
    """

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.chatlab.orca.schemas import PatientInitialOutputSchema as _Schema
    response_schema = _Schema


@service
class GenerateReplyResponse(
    PatientReplyContextInstruction,      # order=0  - dynamic patient context
    CharacterConsistencyInstruction,     # order=10 - character roleplay consistency
    SMSStyleInstruction,                 # order=20 - informal SMS communication style
    PatientReplyDetailInstruction,       # order=50 - reply instructions
    PreviousResponseMixin,
    DjangoBaseService,
):
    """Generate a reply to a user message.

    Expects context with 'user_message' for the user's input.
    """

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


@service
class GenerateImageResponse(
    ImageGenerationInstruction,          # order=50 - image generation instructions
    DjangoBaseService,
):
    """Generate a patient image via Pydantic AI."""

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    # No structured schema - image generation uses tool calling
    response_schema = None
