# chatlab/orca/services/stitch.py
"""Stitch AI facilitator service for ChatLab."""

import logging
from typing import ClassVar

from apps.chatlab.orca.instructions import (
    StitchConversationContextInstruction,
    StitchPersonaInstruction,
    StitchReplyDetailInstruction,
)
from orchestrai_django.components.services import DjangoBaseService, PreviousResponseMixin
from orchestrai_django.decorators import orca

logger = logging.getLogger(__name__)


@orca.service
class GenerateStitchReply(
    PreviousResponseMixin,
    StitchPersonaInstruction,
    StitchConversationContextInstruction,
    StitchReplyDetailInstruction,
    DjangoBaseService,
):
    """Generate a reply from Stitch, the AI facilitator."""

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
