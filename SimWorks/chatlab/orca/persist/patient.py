"""Persistence handlers for patient response schemas."""

import logging
from orchestrai_django.decorators import persistence_handler
from orchestrai_django.components.persistence import BasePersistenceHandler
from orchestrai.types import Response
from chatlab.orca.mixins import ChatlabMixin
from chatlab.orca.schemas import (
    PatientInitialOutputSchema,
    PatientReplyOutputSchema,
    PatientResultsOutputSchema,
)
from chatlab.models import Message
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

        if not created and chunk.domain_object:
            # Already persisted - return existing Message
            logger.info(
                f"Idempotent skip: Message {chunk.object_id} already exists "
                f"for call {chunk.call_id}"
            )
            return chunk.domain_object

        # First persistence - validate and create domain objects
        simulation_id = response.context.get("simulation_id")
        if not simulation_id:
            raise ValueError("Response context missing 'simulation_id'")

        # Type-safe deserialization (already validated by codec)
        data = self.schema.model_validate(response.structured_data)

        # 1. Extract text from messages
        text_content = await self._extract_text_from_messages(data.messages)

        # 2. Create Message
        message = await Message.objects.acreate(
            simulation_id=simulation_id,
            content=text_content,
            role="assistant",
            is_from_ai=True,
            message_type="text",
            sender=None,
        )

        logger.info(
            f"Created Message {message.id} for simulation {simulation_id} "
            f"(schema: PatientInitialOutputSchema)"
        )

        # 3. Persist metadata (polymorphic routing)
        await self._persist_metadata_items(data.metadata, simulation_id)

        # 4. llm_conditions_check - SKIP (not persisted per user decision)

        # Link to idempotency tracker
        from django.contrib.contenttypes.models import ContentType

        chunk.content_type = await ContentType.objects.aget_for_model(Message)
        chunk.object_id = message.id
        await chunk.asave()

        return message

    async def _extract_text_from_messages(self, messages: list) -> str:
        """
        Extract text content from DjangoOutputItem list.

        Navigates message structure to find output_text content.
        """
        text_content = ""

        for msg in messages:
            for content in msg.content:
                if hasattr(content, "type") and content.type == "output_text":
                    text_content = content.text
                    break
            if text_content:
                break

        if not text_content:
            logger.warning("No text content found in messages, using placeholder")
            text_content = "(No content)"

        return text_content

    async def _persist_metadata_items(self, metadata: list, simulation_id: int):
        """
        Persist metadata items to SimulationMetadata.

        Routes to polymorphic models based on item_meta hints.
        For now, uses generic SimulationMetadata. Can be extended to
        route to LabResult, RadResult, etc. based on item structure.

        Args:
            metadata: List of DjangoOutputItem with metadata
            simulation_id: Simulation to attach metadata to
        """
        for meta_item in metadata:
            try:
                # Extract text content
                text = ""
                for content in meta_item.content:
                    if hasattr(content, "type") and content.type == "output_text":
                        text = content.text
                        break

                # Extract key from item_meta
                key = meta_item.item_meta.get("key", "metadata")
                item_type = meta_item.item_meta.get("type")

                # For now, use generic SimulationMetadata
                # TODO: Route to LabResult, RadResult based on item_type
                await SimulationMetadata.objects.acreate(
                    simulation_id=simulation_id,
                    key=key,
                    value=text,
                )

                logger.debug(f"Created metadata: {key} = {text[:50]}...")

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

        if not created and chunk.domain_object:
            # Already persisted - return existing Message
            logger.info(
                f"Idempotent skip: Reply Message {chunk.object_id} already exists "
                f"for call {chunk.call_id}"
            )
            return chunk.domain_object

        # First persistence - validate and create domain objects
        simulation_id = response.context.get("simulation_id")
        if not simulation_id:
            raise ValueError("Response context missing 'simulation_id'")

        # Type-safe deserialization
        data = self.schema.model_validate(response.structured_data)

        # Extract text from messages
        text_content = ""
        for msg in data.messages:
            for content in msg.content:
                if hasattr(content, "type") and content.type == "output_text":
                    text_content = content.text
                    break
            if text_content:
                break

        if not text_content:
            logger.warning("No text content found in reply, using placeholder")
            text_content = "(No content)"

        # Create Message
        message = await Message.objects.acreate(
            simulation_id=simulation_id,
            content=text_content,
            role="assistant",
            is_from_ai=True,
            message_type="text",
            sender=None,
        )

        logger.info(
            f"Created reply Message {message.id} for simulation {simulation_id} "
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
        from django.contrib.contenttypes.models import ContentType

        chunk.content_type = await ContentType.objects.aget_for_model(Message)
        chunk.object_id = message.id
        await chunk.asave()

        return message


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

        if not created and chunk.domain_object:
            # Already persisted - return existing metadata
            logger.info(
                f"Idempotent skip: Results metadata already persisted "
                f"for call {chunk.call_id}"
            )
            # Return empty list since we can't easily retrieve all metadata items
            return []

        # First persistence - validate and create domain objects
        simulation_id = response.context.get("simulation_id")
        if not simulation_id:
            raise ValueError("Response context missing 'simulation_id'")

        # Type-safe deserialization
        data = self.schema.model_validate(response.structured_data)

        # Persist metadata items (scored observations, final assessments)
        metadata_items = await self._persist_results_metadata(data.metadata, simulation_id)

        logger.info(
            f"Persisted {len(metadata_items)} results metadata items for simulation {simulation_id} "
            f"(schema: PatientResultsOutputSchema)"
        )

        # llm_conditions_check - SKIP (not persisted per user decision)

        # Link to idempotency tracker (use first metadata item if available)
        from django.contrib.contenttypes.models import ContentType

        if metadata_items:
            chunk.content_type = await ContentType.objects.aget_for_model(SimulationMetadata)
            chunk.object_id = metadata_items[0].id
            await chunk.asave()

        return metadata_items

    async def _persist_results_metadata(
        self, metadata: list, simulation_id: int
    ) -> list:
        """
        Persist results metadata items to SimulationMetadata.

        Results metadata includes scored observations, final diagnosis assessment,
        treatment plan evaluation, etc.

        Args:
            metadata: List of DjangoOutputItem with results metadata
            simulation_id: Simulation to attach metadata to

        Returns:
            List of created SimulationMetadata instances
        """
        created_items = []

        for meta_item in metadata:
            try:
                # Extract text content
                text = ""
                for content in meta_item.content:
                    if hasattr(content, "type") and content.type == "output_text":
                        text = content.text
                        break

                # Extract key from item_meta
                key = meta_item.item_meta.get("key", "result")
                item_type = meta_item.item_meta.get("type", "assessment")

                # Create metadata record
                metadata_obj = await SimulationMetadata.objects.acreate(
                    simulation_id=simulation_id,
                    key=key,
                    value=text,
                )

                created_items.append(metadata_obj)
                logger.debug(f"Created results metadata: {key} = {text[:50]}...")

            except Exception as exc:
                logger.warning(
                    f"Failed to persist results metadata item: {exc}", exc_info=True
                )
                # Continue with other items

        return created_items
