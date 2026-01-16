"""Persistence handlers for patient response schemas."""

import logging
from asgiref.sync import sync_to_async
from django.contrib.contenttypes.models import ContentType
from orchestrai_django.decorators import persistence_handler
from orchestrai_django.components.persistence import BasePersistenceHandler
from orchestrai.types import Response
from chatlab.orca.mixins import ChatlabMixin
from chatlab.orca.schemas import (
    PatientInitialOutputSchema,
    PatientReplyOutputSchema,
    PatientResultsOutputSchema,
)
from chatlab.models import Message, RoleChoices
from core.utils.accounts import aget_or_create_system_user
from simulation.orca.mixins import StandardizedPatientMixin
from simulation.models import SimulationMetadata

logger = logging.getLogger(__name__)


@persistence_handler
class PatientInitialPersistence(ChatlabMixin, StandardizedPatientMixin, BasePersistenceHandler):
    """
    Persist PatientInitialOutputSchema to chatlab Message + metadata.

    Identity: persist.chatlab.standardized_patient.PatientInitialPersistence
    Handles: (chatlab, schemas.chatlab.standardized_patient.PatientInitialOutputSchema)

    Schema structure:
        - messages: list[DjangoOutputItem] → Message.content
        - metadata: list[DjangoOutputItem] → SimulationMetadata (polymorphic)
        - llm_conditions_check: list[...] → NOT PERSISTED (per user decision)
    """

    schema = PatientInitialOutputSchema

    async def persist(self, response: Response) -> Message:
        """
        Extract and persist patient initial response.

        Args:
            response: Full Response with:
                - structured_data: PatientInitialOutputSchema instance
                - context: {"simulation_id": int, ...}

        Returns:
            Created Message instance

        Raises:
            ValueError: If simulation_id missing from context
        """
        # Idempotency check - ensure exactly-once persistence
        chunk, created = await self.ensure_idempotent(response)

        if not created and chunk.object_id:
            # Already persisted - fetch and return existing Message
            existing_message = await Message.objects.aget(id=chunk.object_id)
            logger.info(
                f"Idempotent skip: Message {chunk.object_id} already exists "
                f"for call {chunk.call_id}"
            )
            return existing_message

        # First persistence - validate and create domain objects
        simulation_id = response.context.get("simulation_id")
        if not simulation_id:
            raise ValueError("Response context missing 'simulation_id'")

        # Get ai_response_audit_id for linking
        ai_response_audit_id = (response.context or {}).get("_ai_response_audit_id")

        # Type-safe deserialization (already validated by codec)
        data = self.schema.model_validate(response.structured_data)

        # 1. Persist ALL messages (not just the first one)
        messages = await self._persist_all_messages(
            data.messages, simulation_id, ai_response_audit_id
        )

        if not messages:
            raise ValueError("No messages with text content to persist")

        # Return first message for backwards compatibility
        message = messages[0]

        logger.info(
            f"Created {len(messages)} Message(s) for simulation {simulation_id} "
            f"(schema: PatientInitialOutputSchema)"
        )

        # 2. Persist metadata (polymorphic routing)
        await self._persist_metadata_items(data.metadata, simulation_id, ai_response_audit_id)

        # 5. llm_conditions_check - SKIP (not persisted per user decision)

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
        """
        Persist ALL message items as separate Message objects.

        Args:
            messages: List of DjangoOutputItem with message content
            simulation_id: Simulation to attach messages to
            ai_response_audit_id: Optional AI audit record ID to link

        Returns:
            List of created Message instances
        """
        system_user = await aget_or_create_system_user()
        created_messages = []

        for msg in messages:
            # Extract text from this message
            text_content = ""
            for content in msg.content:
                if hasattr(content, "type") and content.type in ("text", "output_text"):
                    text_content = content.text
                    break

            if not text_content:
                logger.debug("Skipping message without text content")
                continue  # Skip messages without text content

            message = await Message.objects.acreate(
                simulation_id=simulation_id,
                content=text_content,
                role=RoleChoices.ASSISTANT,
                is_from_ai=True,
                message_type="text",
                sender=system_user,
            )

            # Link ai_response_audit if available
            if ai_response_audit_id:
                message.ai_response_audit_id = ai_response_audit_id
                await message.asave(update_fields=["ai_response_audit"])

            created_messages.append(message)
            logger.debug(f"Created Message {message.id}: {text_content[:50]}...")

        return created_messages

    async def _persist_metadata_items(
        self, metadata: list, simulation_id: int, ai_response_audit_id: int | None = None
    ):
        """
        Persist metadata items to SimulationMetadata.

        PatientInitialOutputSchema uses list[ResultMetafield] for metadata,
        which is a simple key-value pair format.

        Args:
            metadata: List of ResultMetafield (key-value pairs)
            simulation_id: Simulation to attach metadata to
            ai_response_audit_id: Optional AI audit record ID to link
        """
        for meta_item in metadata:
            try:
                # ResultMetafield has key and value directly
                key = meta_item.key
                value = str(meta_item.value) if meta_item.value is not None else ""

                metadata_obj = await SimulationMetadata.objects.acreate(
                    simulation_id=simulation_id,
                    key=key,
                    value=value,
                )

                # Link ai_response_audit if available
                if ai_response_audit_id:
                    metadata_obj.ai_response_audit_id = ai_response_audit_id
                    await metadata_obj.asave(update_fields=["ai_response_audit"])

                logger.debug(f"Created metadata: {key} = {value[:50] if value else '(empty)'}...")

            except Exception as exc:
                logger.warning(f"Failed to persist metadata item: {exc}", exc_info=True)
                # Continue with other items


@persistence_handler
class PatientReplyPersistence(ChatlabMixin, StandardizedPatientMixin, BasePersistenceHandler):
    """
    Persist PatientReplyOutputSchema to chatlab Message.

    Identity: persist.chatlab.standardized_patient.PatientReplyPersistence
    Handles: (chatlab, schemas.chatlab.standardized_patient.PatientReplyOutputSchema)

    Schema structure:
        - image_requested: bool → Could trigger image generation workflow
        - messages: list[DjangoOutputItem] → Message.content
        - llm_conditions_check: list[...] → NOT PERSISTED
    """

    schema = PatientReplyOutputSchema

    async def persist(self, response: Response) -> Message:
        """
        Extract and persist patient reply response.

        Similar to PatientInitialPersistence but for reply schema.
        """
        # Idempotency check - ensure exactly-once persistence
        chunk, created = await self.ensure_idempotent(response)

        if not created and chunk.object_id:
            # Already persisted - fetch and return existing Message
            existing_message = await Message.objects.aget(id=chunk.object_id)
            logger.info(
                f"Idempotent skip: Reply Message {chunk.object_id} already exists "
                f"for call {chunk.call_id}"
            )
            return existing_message

        # First persistence - validate and create domain objects
        simulation_id = response.context.get("simulation_id")
        if not simulation_id:
            raise ValueError("Response context missing 'simulation_id'")

        # Get ai_response_audit_id for linking
        ai_response_audit_id = (response.context or {}).get("_ai_response_audit_id")

        # Type-safe deserialization
        data = self.schema.model_validate(response.structured_data)

        # Persist ALL messages (not just the first one)
        messages = await self._persist_all_messages(
            data.messages, simulation_id, ai_response_audit_id
        )

        if not messages:
            raise ValueError("No messages with text content to persist")

        # Return first message for backwards compatibility
        message = messages[0]

        logger.info(
            f"Created {len(messages)} reply Message(s) for simulation {simulation_id} "
            f"(schema: PatientReplyOutputSchema)"
        )

        # Check if image was requested
        if data.image_requested:
            logger.info(
                f"Image requested for simulation {simulation_id}, "
                f"image generation workflow should trigger"
            )
            # TODO: Trigger image generation workflow if needed

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
        """
        Persist ALL message items as separate Message objects.

        Args:
            messages: List of DjangoOutputItem with message content
            simulation_id: Simulation to attach messages to
            ai_response_audit_id: Optional AI audit record ID to link

        Returns:
            List of created Message instances
        """
        system_user = await aget_or_create_system_user()
        created_messages = []

        for msg in messages:
            # Extract text from this message
            text_content = ""
            for content in msg.content:
                if hasattr(content, "type") and content.type in ("text", "output_text"):
                    text_content = content.text
                    break

            if not text_content:
                logger.debug("Skipping message without text content")
                continue  # Skip messages without text content

            message = await Message.objects.acreate(
                simulation_id=simulation_id,
                content=text_content,
                role=RoleChoices.ASSISTANT,
                is_from_ai=True,
                message_type="text",
                sender=system_user,
            )

            # Link ai_response_audit if available
            if ai_response_audit_id:
                message.ai_response_audit_id = ai_response_audit_id
                await message.asave(update_fields=["ai_response_audit"])

            created_messages.append(message)
            logger.debug(f"Created reply Message {message.id}: {text_content[:50]}...")

        return created_messages


@persistence_handler
class PatientResultsPersistence(ChatlabMixin, StandardizedPatientMixin, BasePersistenceHandler):
    """
    Persist PatientResultsOutputSchema to SimulationMetadata.

    Identity: persist.chatlab.standardized_patient.PatientResultsPersistence
    Handles: (chatlab, schemas.chatlab.standardized_patient.PatientResultsOutputSchema)

    Schema structure:
        - metadata: list[DjangoOutputItem] → SimulationMetadata (scored observations, assessments)
        - llm_conditions_check: list[...] → NOT PERSISTED

    Unlike PatientInitialPersistence and PatientReplyPersistence, this handler
    does NOT create a Message because PatientResultsOutputSchema contains only
    metadata/scoring, not user-facing messages.
    """

    schema = PatientResultsOutputSchema

    async def persist(self, response: Response) -> list:
        """
        Extract and persist patient results metadata.

        Args:
            response: Full Response with:
                - structured_data: PatientResultsOutputSchema instance
                - context: {"simulation_id": int, ...}

        Returns:
            List of created SimulationMetadata instances

        Raises:
            ValueError: If simulation_id missing from context
        """
        # Idempotency check - ensure exactly-once persistence
        chunk, created = await self.ensure_idempotent(response)

        if not created and chunk.object_id:
            # Already persisted - retrieve existing metadata items
            logger.info(
                f"Idempotent skip: Results metadata already persisted "
                f"for call {chunk.call_id}"
            )
            # Retrieve existing metadata items from chunk metadata
            if hasattr(chunk, 'metadata') and chunk.metadata:
                metadata_ids = chunk.metadata.get('metadata_item_ids', [])
                if metadata_ids:
                    metadata_items = await SimulationMetadata.objects.filter(
                        id__in=metadata_ids
                    ).ato_list()
                    return list(metadata_items)
            # Fallback: return empty list if metadata not available
            return []

        # First persistence - validate and create domain objects
        simulation_id = response.context.get("simulation_id")
        if not simulation_id:
            raise ValueError("Response context missing 'simulation_id'")

        # Get ai_response_audit_id for linking
        ai_response_audit_id = (response.context or {}).get("_ai_response_audit_id")

        # Type-safe deserialization
        data = self.schema.model_validate(response.structured_data)

        # Persist metadata items (scored observations, final assessments)
        metadata_items = await self._persist_results_metadata(
            data.metadata, simulation_id, ai_response_audit_id
        )

        logger.info(
            f"Persisted {len(metadata_items)} results metadata items for simulation {simulation_id} "
            f"(schema: PatientResultsOutputSchema)"
        )

        # llm_conditions_check - SKIP (not persisted per user decision)

        # Link to idempotency tracker (store all metadata item IDs)
        if metadata_items:
            # Store all metadata item IDs in chunk metadata for idempotency
            chunk.metadata = {
                "metadata_item_ids": [item.id for item in metadata_items],
                "count": len(metadata_items),
            }
            # Link primary object for domain_object accessor
            chunk.content_type = await sync_to_async(ContentType.objects.get_for_model)(SimulationMetadata)
            chunk.object_id = metadata_items[0].id
            await chunk.asave()

        return metadata_items

    async def _persist_results_metadata(
        self, metadata: list, simulation_id: int, ai_response_audit_id: int | None = None
    ) -> list:
        """
        Persist results metadata items to SimulationMetadata.

        Results metadata includes scored observations, final diagnosis assessment,
        treatment plan evaluation, etc.

        Args:
            metadata: List of DjangoOutputItem with results metadata
            simulation_id: Simulation to attach metadata to
            ai_response_audit_id: Optional AI audit record ID to link

        Returns:
            List of created SimulationMetadata instances
        """
        created_items = []

        for meta_item in metadata:
            try:
                # Extract text content
                # Supports both ResultTextContent (type="text") and OutputTextContent (type="output_text")
                text = ""
                for content in meta_item.content:
                    if hasattr(content, "type") and content.type in ("text", "output_text"):
                        text = content.text
                        break

                # Extract key from item_meta (list[ResultMetafield])
                key = "result"  # default
                item_type = "assessment"  # default
                for metafield in meta_item.item_meta:
                    if metafield.key == "key":
                        key = str(metafield.value) if metafield.value else "result"
                    elif metafield.key == "type":
                        item_type = str(metafield.value) if metafield.value else "assessment"

                # Create metadata record
                metadata_obj = await SimulationMetadata.objects.acreate(
                    simulation_id=simulation_id,
                    key=key,
                    value=text,
                )

                # Link ai_response_audit if available
                if ai_response_audit_id:
                    metadata_obj.ai_response_audit_id = ai_response_audit_id
                    await metadata_obj.asave(update_fields=["ai_response_audit"])

                created_items.append(metadata_obj)
                logger.debug(f"Created results metadata: {key} = {text[:50] if text else '(empty)'}...")

            except Exception as exc:
                logger.warning(
                    f"Failed to persist results metadata item: {exc}",
                    exc_info=True,
                    extra={
                        "simulation_id": simulation_id,
                        "metadata_key": key,
                        "item_type": item_type,
                        "text_preview": text[:100] if text else "(empty)",
                    }
                )
                # Continue with other items

        return created_items
