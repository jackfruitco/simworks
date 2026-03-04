# chatlab/orca/services/stitch.py
"""
Stitch AI facilitator service for ChatLab.

Stitch is a friendly AI medical education facilitator that helps students
reflect on their simulation performance after the simulation ends.
Stitch has full context of the patient conversation and simulation metadata.

Services compose instructions via MRO inheritance from BaseInstruction classes.
Pydantic AI handles execution and validation.
"""

import logging
from typing import ClassVar

from apps.chatlab.orca.instructions import (
    StitchConversationContextInstruction,
    StitchPersonaInstruction,
    StitchReplyDetailInstruction,
)
from orchestrai_django.components.services import DjangoBaseService, PreviousResponseMixin
from orchestrai_django.decorators import service

logger = logging.getLogger(__name__)


@service
class GenerateStitchReply(
    StitchPersonaInstruction,                 # order=0  - dynamic persona + sim context
    StitchConversationContextInstruction,     # order=50 - dynamic history fetch
    StitchReplyDetailInstruction,             # order=90 - static reply rules
    PreviousResponseMixin,
    DjangoBaseService,
):
    """Generate a reply from Stitch, the AI facilitator.

    Stitch helps students debrief after a simulation — answering clinical
    questions, providing educational context, and encouraging reflection.

    Identity: services.chatlab.stitch.GenerateStitchReply
    """

    required_context_keys: ClassVar[tuple[str, ...]] = (
        "simulation_id",
        "conversation_id",
    )
    use_native_output = True

    from apps.chatlab.orca.schemas.stitch import StitchReplyOutputSchema as _Schema
    response_schema = _Schema

    async def _aprepare_context(self) -> None:
        """Populate user_message from stored user message ID."""
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
