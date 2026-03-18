# chatlab/orca/services/stitch.py
"""Stitch AI facilitator service for ChatLab."""

import logging
from typing import ClassVar

from orchestrai_django.components.services import DjangoBaseService, PreviousResponseMixin
from orchestrai_django.decorators import orca

logger = logging.getLogger(__name__)


@orca.service
class GenerateStitchReply(PreviousResponseMixin, DjangoBaseService):
    """Generate a reply from Stitch, the AI facilitator."""

    instruction_refs: ClassVar[list[str]] = [
        "chatlab.stitch.StitchPersonaInstruction",
        "chatlab.stitch.StitchRoleInstruction",
        "chatlab.stitch.StitchConversationContextInstruction",
        "chatlab.stitch.StitchDebriefInstruction",
        "chatlab.stitch.StitchSchemaContractInstruction",
        "chatlab.stitch.StitchToneInstruction",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = (
        "simulation_id",
        "conversation_id",
    )
    use_native_output = True

    from apps.chatlab.orca.schemas.stitch import StitchReplyOutputSchema as _Schema

    response_schema = _Schema

    async def _aset_previous_response_fallback(self) -> None:
        """Fallback previous_response_id for initial Stitch turns.

        PreviousResponseMixin scopes lookup to this service identity. For the
        first Stitch turn there is no prior Stitch call, so we fall back to the
        latest completed call for the simulation (typically patient dialogue).
        """
        if self.context.get("previous_response_id") is not None:
            return

        simulation_id = self.context.get("simulation_id")
        if simulation_id is None:
            return

        try:
            from orchestrai_django.models import CallStatus, ServiceCall as ServiceCallModel

            prev_call = (
                await ServiceCallModel.objects.filter(
                    related_object_id=str(simulation_id),
                    status=CallStatus.COMPLETED,
                    provider_response_id__isnull=False,
                )
                .exclude(service_identity__isnull=True)
                .order_by("-finished_at")
                .afirst()
            )
        except Exception as exc:
            logger.warning(
                "Unable to resolve cross-service previous response ID for simulation %s: %s",
                simulation_id,
                exc,
            )
            return

        if not prev_call or not prev_call.provider_response_id:
            return

        prev_id = prev_call.provider_response_id
        self.context["previous_response_id"] = prev_id
        self.context["previous_provider_response_id"] = prev_id

    async def _aprepare_context(self) -> None:
        """Populate user_message from stored user message ID."""
        if hasattr(super(), "_aprepare_context"):
            await super()._aprepare_context()

        await self._aset_previous_response_fallback()

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
