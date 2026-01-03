"""Persistence handlers for feedback schemas."""

import logging
from orchestrai_django.decorators import persistence_handler
from orchestrai_django.components.persistence import BasePersistenceHandler
from orchestrai.types import Response
from simulation.orca.mixins import SimcoreMixin, FeedbackMixin
from simulation.orca.schemas.feedback import HotwashInitialSchema
from simulation.models import SimulationFeedback

logger = logging.getLogger(__name__)


@persistence_handler
class HotwashInitialPersistence(SimcoreMixin, FeedbackMixin, BasePersistenceHandler):
    """
    Persist HotwashInitialSchema to SimulationFeedback.

    Identity: persist.simcore.feedback.HotwashInitialPersistence
    Handles: (simcore, schemas.simcore.feedback.HotwashInitialSchema)

    Schema structure:
        - metadata: HotwashInitialBlock → SimulationFeedback (multiple records)
            - correct_diagnosis: bool → key="hotwash_correct_diagnosis"
            - correct_treatment_plan: bool → key="hotwash_correct_treatment_plan"
            - patient_experience: int → key="hotwash_patient_experience"
            - overall_feedback: str → key="hotwash_overall_feedback"
        - llm_conditions_check: list[...] → NOT PERSISTED
    """

    schema = HotwashInitialSchema

    async def persist(self, response: Response) -> list:
        """
        Extract and persist hotwash initial feedback.

        Args:
            response: Full Response with:
                - structured_data: HotwashInitialSchema instance
                - context: {"simulation_id": int, ...}

        Returns:
            List of created SimulationFeedback instances

        Raises:
            ValueError: If simulation_id missing from context
        """
        # Idempotency check - ensure exactly-once persistence
        chunk, created = await self.ensure_idempotent(response)

        if not created and chunk.domain_object:
            # Already persisted - retrieve existing feedback items
            logger.info(
                f"Idempotent skip: Hotwash feedback already persisted "
                f"for call {chunk.call_id}"
            )
            # Retrieve existing feedback items from metadata or query
            if hasattr(chunk, 'metadata') and chunk.metadata:
                feedback_ids = chunk.metadata.get('feedback_item_ids', [])
                if feedback_ids:
                    feedback_items = await SimulationFeedback.objects.filter(
                        id__in=feedback_ids
                    ).ato_list()
                    return list(feedback_items)
            # Fallback: return empty list if metadata not available
            return []

        # First persistence - validate and create domain objects
        simulation_id = response.context.get("simulation_id")
        if not simulation_id:
            raise ValueError("Response context missing 'simulation_id'")

        # Type-safe deserialization
        data = self.schema.model_validate(response.structured_data)

        # Persist feedback items
        feedback_items = await self._persist_feedback_block(
            data.metadata, simulation_id
        )

        logger.info(
            f"Persisted {len(feedback_items)} hotwash feedback items for simulation {simulation_id} "
            f"(schema: HotwashInitialSchema)"
        )

        # llm_conditions_check - SKIP (not persisted per user decision)

        # Link to idempotency tracker (store all feedback item IDs)
        from django.contrib.contenttypes.models import ContentType

        if feedback_items:
            # Store all feedback item IDs in chunk metadata for idempotency
            chunk.metadata = {
                "feedback_item_ids": [item.id for item in feedback_items],
                "count": len(feedback_items),
            }
            # Link primary object for domain_object accessor
            chunk.content_type = await ContentType.objects.aget_for_model(
                SimulationFeedback
            )
            chunk.object_id = feedback_items[0].id
            await chunk.asave()

        return feedback_items

    async def _persist_feedback_block(
        self, feedback_block, simulation_id: int
    ) -> list:
        """
        Persist HotwashInitialBlock to SimulationFeedback records.

        Creates individual feedback records for each field in the block.

        Args:
            feedback_block: HotwashInitialBlock with feedback data
            simulation_id: Simulation to attach feedback to

        Returns:
            List of created SimulationFeedback instances
        """
        feedback_items = []

        # Map block fields to database keys
        feedback_mapping = [
            ("hotwash_correct_diagnosis", str(feedback_block.correct_diagnosis)),
            ("hotwash_correct_treatment_plan", str(feedback_block.correct_treatment_plan)),
            ("hotwash_patient_experience", str(feedback_block.patient_experience)),
            ("hotwash_overall_feedback", feedback_block.overall_feedback),
        ]

        for key, value in feedback_mapping:
            try:
                # Create or update feedback record
                feedback_obj, created = await SimulationFeedback.objects.aupdate_or_create(
                    simulation_id=simulation_id,
                    key=key,
                    defaults={"value": value},
                )

                feedback_items.append(feedback_obj)
                action = "Created" if created else "Updated"
                logger.debug(f"{action} feedback: {key} = {value[:50] if len(value) > 50 else value}...")

            except Exception as exc:
                logger.warning(
                    f"Failed to persist feedback item: {exc}",
                    exc_info=True,
                    extra={
                        "simulation_id": simulation_id,
                        "feedback_key": key,
                        "value_preview": value[:100] if isinstance(value, str) else str(value),
                    }
                )
                # Continue with other items

        return feedback_items
