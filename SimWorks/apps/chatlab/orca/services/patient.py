# chatlab/orca/services/patient.py
"""Patient AI services for ChatLab using class-based instructions."""

import logging
from typing import ClassVar

from asgiref.sync import sync_to_async

from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import orca

logger = logging.getLogger(__name__)


class _PatientProviderConversationMixin:
    """Prepare one durable Responses conversation for patient service runs."""

    async def _aprepare_patient_provider_context(self) -> None:
        from apps.chatlab.ai.context import build_patient_runtime_context
        from apps.chatlab.ai.conversations import (
            ensure_provider_conversation,
            sync_messages_to_provider,
        )
        from apps.simcore.models import Conversation

        conversation_id = self.context.get("conversation_id")
        if not conversation_id:
            conversation_id = (
                await Conversation.objects.filter(
                    simulation_id=self.context.get("simulation_id"),
                    conversation_type__slug="simulated_patient",
                )
                .values_list("pk", flat=True)
                .afirst()
            )
        if not conversation_id:
            return

        conversation = await Conversation.objects.select_related("conversation_type").aget(
            pk=conversation_id,
            simulation_id=self.context.get("simulation_id"),
        )
        runtime_context = await build_patient_runtime_context(
            simulation_id=self.context.get("simulation_id"),
            conversation=conversation,
        )
        provider_conversation = await sync_to_async(ensure_provider_conversation)(conversation)

        user_message_id = self.context.get("user_msg") or self.context.get("user_msg_id")
        await sync_to_async(sync_messages_to_provider)(
            conversation,
            through_message_id=(int(user_message_id) - 1 if user_message_id else None),
        )
        self.context["conversation_id"] = conversation.pk
        self.context["patient_runtime_context"] = runtime_context.as_dict()
        model_settings = dict(self.context.get("model_settings") or {})
        model_settings.pop("openai_previous_response_id", None)
        model_settings.pop("previous_response_id", None)
        self.context.pop("openai_previous_response_id", None)
        self.context.pop("previous_response_id", None)
        self.context.pop("previous_provider_response_id", None)
        model_settings["openai_conversation_id"] = provider_conversation.id
        self.context["model_settings"] = model_settings

    async def _aprepare_context(self) -> None:
        if hasattr(super(), "_aprepare_context"):
            await super()._aprepare_context()
        await self._aprepare_patient_provider_context()

    async def on_success(self, context, result) -> None:
        if hasattr(super(), "on_success"):
            await super().on_success(context, result)

        user_message_id = context.get("user_msg") or context.get("user_msg_id")
        conversation_id = context.get("conversation_id")
        if not user_message_id or not conversation_id:
            return

        from apps.chatlab.ai.conversations import mark_message_synced_to_provider
        from apps.chatlab.models import Message
        from apps.simcore.models import Conversation

        provider_response_id = getattr(
            getattr(result, "response", None), "provider_response_id", None
        )
        if not provider_response_id:
            return
        conversation = await Conversation.objects.aget(pk=conversation_id)
        message = await Message.objects.aget(pk=user_message_id)
        await sync_to_async(mark_message_synced_to_provider)(
            conversation=conversation,
            message=message,
            provider_item_id=f"responses:{provider_response_id}:input:{message.pk}",
        )

    async def on_failure(self, context, error) -> None:
        """Clear an unrecoverable provider ID so the next retry can rebuild it."""

        if hasattr(super(), "on_failure"):
            await super().on_failure(context, error)
        if "not found" not in str(error).lower() or not context.get("conversation_id"):
            return

        from apps.chatlab.ai.conversations import rebuild_provider_conversation
        from apps.simcore.models import Conversation

        try:
            conversation = await Conversation.objects.aget(pk=context["conversation_id"])
            await sync_to_async(rebuild_provider_conversation)(conversation)
        except Exception:
            logger.warning(
                "Unable to rebuild provider conversation after failed patient response",
                exc_info=True,
            )


@orca.service
class GenerateInitialResponse(_PatientProviderConversationMixin, DjangoBaseService):
    """Generate the initial patient response."""

    instruction_refs: ClassVar[list[str]] = [
        "chatlab.patient.PatientNameInstruction",
        "chatlab.patient.PatientModifierInstruction",
        "chatlab.patient.PatientSafetyBoundariesInstruction",
        "chatlab.patient.PatientConversationBehaviorInstruction",
        "chatlab.patient.PatientInformationDisclosureInstruction",
        "chatlab.patient.PatientSchemaContractInstruction",
        "chatlab.patient.PatientRecentScenarioHistoryInstruction",
        "chatlab.patient.PatientInitialDetailInstruction",
    ]
    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.chatlab.orca.schemas import PatientInitialOutputSchema as _Schema

    response_schema = _Schema


@orca.service
class GenerateReplyResponse(_PatientProviderConversationMixin, DjangoBaseService):
    """Generate a reply to a user message."""

    instruction_refs: ClassVar[list[str]] = [
        "chatlab.patient.PatientNameInstruction",
        "chatlab.patient.PatientSafetyBoundariesInstruction",
        "chatlab.patient.PatientConversationBehaviorInstruction",
        "chatlab.patient.PatientInformationDisclosureInstruction",
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
