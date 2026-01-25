"""Persistence handlers for patient response schemas.

Simplified for Pydantic AI - no identity system required.
Handlers are registered by schema class.
"""

import logging
from typing import Any

from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType

from orchestrai_django.decorators import persistence_handler
from orchestrai_django.components.persistence import BasePersistenceHandler
from chatlab.orca.schemas import (
    PatientInitialOutputSchema,
    PatientReplyOutputSchema,
    PatientResultsOutputSchema,
)
from chatlab.models import Message, RoleChoices
from core.utils.accounts import aget_or_create_system_user
from simulation.models import SimulationMetadata

logger = logging.getLogger(__name__)


@persistence_handler
class PatientInitialPersistence(BasePersistenceHandler):
    """
    Persist PatientInitialOutputSchema to chatlab Message + metadata.

    Schema structure:
        - messages: list[ResultMessageItem] → Message.content
        - metadata: list[ResultMetafield] → SimulationMetadata
        - llm_conditions_check: list[...] → NOT PERSISTED
    """

    schema = PatientInitialOutputSchema

    async def persist(self, *, data: Any, context: dict[str, Any]) -> Message:
        """
        Extract and persist patient initial response.

        Args:
            data: PatientInitialOutputSchema instance (validated by Pydantic AI)
            context: {"simulation_id": int, "call_id": str, ...}

        Returns:
            Created Message instance
        """
        call_id = context.get("call_id", "")
        simulation_id = context.get("simulation_id")

        if not simulation_id:
            raise ValueError("Context missing 'simulation_id'")

        # Idempotency check
        chunk, created = await self.ensure_idempotent(call_id=call_id, context=context)

        if not created and chunk.object_id:
            existing_message = await Message.objects.aget(id=chunk.object_id)
            logger.info(f"Idempotent skip: Message {chunk.object_id} already exists")
            return existing_message

        # Validate data if it's a dict
        if isinstance(data, dict):
            data = self.schema.model_validate(data)

        ai_response_audit_id = context.get("_ai_response_audit_id")

        # Persist messages
        messages = await self._persist_all_messages(
            data.messages, simulation_id, ai_response_audit_id
        )

        if not messages:
            raise ValueError("No messages with text content to persist")

        message = messages[0]

        logger.info(
            f"Created {len(messages)} Message(s) for simulation {simulation_id}"
        )

        # Persist metadata
        await self._persist_metadata_items(data.metadata, simulation_id, ai_response_audit_id)

        # Link to idempotency tracker
        chunk.content_type = await sync_to_async(ContentType.objects.get_for_model)(Message)
        chunk.object_id = message.id
        await chunk.asave()

        return message

    async def _persist_all_messages(
        self,
        messages: list,
        simulation_id: int,
        ai_response_audit_id: int | None = None,
    ) -> list[Message]:
        """Persist all message items as separate Message objects."""
        from simulation.models import Simulation

        system_user = await aget_or_create_system_user()
        created_messages = []

        simulation = await Simulation.objects.aget(id=simulation_id)
        display_name = simulation.sim_patient_display_name or "AI"

        for msg in messages:
            text_content = ""
            for content in msg.content:
                if hasattr(content, "type") and content.type in ("text", "output_text"):
                    text_content = content.text
                    break

            if not text_content:
                continue

            message = await Message.objects.acreate(
                simulation_id=simulation_id,
                content=text_content,
                role=RoleChoices.ASSISTANT,
                is_from_ai=True,
                message_type="text",
                sender=system_user,
                display_name=display_name,
            )

            if ai_response_audit_id:
                message.ai_response_audit_id = ai_response_audit_id
                await message.asave(update_fields=["ai_response_audit"])

            created_messages.append(message)

        return created_messages

    async def _persist_metadata_items(
        self, metadata: list, simulation_id: int, ai_response_audit_id: int | None = None
    ):
        """Persist metadata items to SimulationMetadata."""
        for meta_item in metadata:
            try:
                key = meta_item.key
                value = str(meta_item.value) if meta_item.value is not None else ""

                metadata_obj = await SimulationMetadata.objects.acreate(
                    simulation_id=simulation_id,
                    key=key,
                    value=value,
                )

                if ai_response_audit_id:
                    metadata_obj.ai_response_audit_id = ai_response_audit_id
                    await metadata_obj.asave(update_fields=["ai_response_audit"])

            except Exception as exc:
                logger.warning(f"Failed to persist metadata item: {exc}", exc_info=True)


@persistence_handler
class PatientReplyPersistence(BasePersistenceHandler):
    """
    Persist PatientReplyOutputSchema to chatlab Message.

    Schema structure:
        - image_requested: bool → May trigger image generation
        - messages: list[ResultMessageItem] → Message.content
        - llm_conditions_check: list[...] → NOT PERSISTED
    """

    schema = PatientReplyOutputSchema

    async def persist(self, *, data: Any, context: dict[str, Any]) -> Message:
        """Extract and persist patient reply response."""
        call_id = context.get("call_id", "")
        simulation_id = context.get("simulation_id")

        if not simulation_id:
            raise ValueError("Context missing 'simulation_id'")

        # Idempotency check
        chunk, created = await self.ensure_idempotent(call_id=call_id, context=context)

        if not created and chunk.object_id:
            existing_message = await Message.objects.aget(id=chunk.object_id)
            logger.info(f"Idempotent skip: Reply Message {chunk.object_id} already exists")
            return existing_message

        # Validate data if it's a dict
        if isinstance(data, dict):
            data = self.schema.model_validate(data)

        ai_response_audit_id = context.get("_ai_response_audit_id")

        # Persist messages
        messages = await self._persist_all_messages(
            data.messages, simulation_id, ai_response_audit_id
        )

        if not messages:
            raise ValueError("No messages with text content to persist")

        message = messages[0]

        logger.info(
            f"Created {len(messages)} reply Message(s) for simulation {simulation_id}"
        )

        if data.image_requested:
            logger.info(f"Image requested for simulation {simulation_id}")

        # Link to idempotency tracker
        chunk.content_type = await sync_to_async(ContentType.objects.get_for_model)(Message)
        chunk.object_id = message.id
        await chunk.asave()

        return message

    async def _persist_all_messages(
        self,
        messages: list,
        simulation_id: int,
        ai_response_audit_id: int | None = None,
    ) -> list[Message]:
        """Persist all message items as separate Message objects."""
        from simulation.models import Simulation

        system_user = await aget_or_create_system_user()
        created_messages = []

        simulation = await Simulation.objects.aget(id=simulation_id)
        display_name = simulation.sim_patient_display_name or "AI"

        for msg in messages:
            text_content = ""
            for content in msg.content:
                if hasattr(content, "type") and content.type in ("text", "output_text"):
                    text_content = content.text
                    break

            if not text_content:
                continue

            message = await Message.objects.acreate(
                simulation_id=simulation_id,
                content=text_content,
                role=RoleChoices.ASSISTANT,
                is_from_ai=True,
                message_type="text",
                sender=system_user,
                display_name=display_name,
            )

            if ai_response_audit_id:
                message.ai_response_audit_id = ai_response_audit_id
                await message.asave(update_fields=["ai_response_audit"])

            created_messages.append(message)

        return created_messages


@persistence_handler
class PatientResultsPersistence(BasePersistenceHandler):
    """
    Persist PatientResultsOutputSchema to SimulationMetadata.

    Schema structure:
        - metadata: list[ResultMessageItem] → SimulationMetadata
        - llm_conditions_check: list[...] → NOT PERSISTED

    This handler does NOT create a Message - only metadata/scoring.
    """

    schema = PatientResultsOutputSchema

    async def persist(self, *, data: Any, context: dict[str, Any]) -> list:
        """Extract and persist patient results metadata."""
        call_id = context.get("call_id", "")
        simulation_id = context.get("simulation_id")

        if not simulation_id:
            raise ValueError("Context missing 'simulation_id'")

        # Idempotency check
        chunk, created = await self.ensure_idempotent(call_id=call_id, context=context)

        if not created and chunk.object_id:
            logger.info("Idempotent skip: Results metadata already persisted")
            if hasattr(chunk, 'metadata') and chunk.metadata:
                metadata_ids = chunk.metadata.get('metadata_item_ids', [])
                if metadata_ids:
                    return list(await SimulationMetadata.objects.filter(
                        id__in=metadata_ids
                    ).ato_list())
            return []

        # Validate data if it's a dict
        if isinstance(data, dict):
            data = self.schema.model_validate(data)

        ai_response_audit_id = context.get("_ai_response_audit_id")

        # Persist metadata
        metadata_items = await self._persist_results_metadata(
            data.metadata, simulation_id, ai_response_audit_id
        )

        logger.info(
            f"Persisted {len(metadata_items)} results metadata items for simulation {simulation_id}"
        )

        # Link to idempotency tracker
        if metadata_items:
            chunk.metadata = {
                "metadata_item_ids": [item.id for item in metadata_items],
                "count": len(metadata_items),
            }
            chunk.content_type = await sync_to_async(ContentType.objects.get_for_model)(SimulationMetadata)
            chunk.object_id = metadata_items[0].id
            await chunk.asave()

        return metadata_items

    async def _persist_results_metadata(
        self, metadata: list, simulation_id: int, ai_response_audit_id: int | None = None
    ) -> list:
        """Persist results metadata items to SimulationMetadata."""
        created_items = []

        for meta_item in metadata:
            try:
                text = ""
                for content in meta_item.content:
                    if hasattr(content, "type") and content.type in ("text", "output_text"):
                        text = content.text
                        break

                key = "result"
                for metafield in meta_item.item_meta:
                    if metafield.key == "key":
                        key = str(metafield.value) if metafield.value else "result"
                        break

                metadata_obj = await SimulationMetadata.objects.acreate(
                    simulation_id=simulation_id,
                    key=key,
                    value=text,
                )

                if ai_response_audit_id:
                    metadata_obj.ai_response_audit_id = ai_response_audit_id
                    await metadata_obj.asave(update_fields=["ai_response_audit"])

                created_items.append(metadata_obj)

            except Exception as exc:
                logger.warning(f"Failed to persist results metadata item: {exc}", exc_info=True)

        return created_items
