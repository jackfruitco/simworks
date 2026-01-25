"""Persistence handlers for feedback schemas.

Simplified for Pydantic AI - no identity system required.
"""

import logging
from typing import Any

from django.contrib.contenttypes.models import ContentType

from orchestrai_django.decorators import persistence_handler
from orchestrai_django.components.persistence import BasePersistenceHandler
from simulation.orca.schemas.feedback import HotwashInitialSchema
from simulation.models import SimulationFeedback

logger = logging.getLogger(__name__)


@persistence_handler
class HotwashInitialPersistence(BasePersistenceHandler):
    """
    Persist HotwashInitialSchema to SimulationFeedback.

    Schema structure:
        - metadata: HotwashInitialBlock → SimulationFeedback (multiple records)
            - correct_diagnosis: bool
            - correct_treatment_plan: bool
            - patient_experience: int
            - overall_feedback: str
        - llm_conditions_check: list[...] → NOT PERSISTED
    """

    schema = HotwashInitialSchema

    async def persist(self, *, data: Any, context: dict[str, Any]) -> list:
        """
        Extract and persist hotwash initial feedback.

        Args:
            data: HotwashInitialSchema instance (validated by Pydantic AI)
            context: {"simulation_id": int, "call_id": str, ...}

        Returns:
            List of created SimulationFeedback instances
        """
        call_id = context.get("call_id", "")
        simulation_id = context.get("simulation_id")

        if not simulation_id:
            raise ValueError("Context missing 'simulation_id'")

        # Idempotency check
        chunk, created = await self.ensure_idempotent(call_id=call_id, context=context)

        if not created and chunk.object_id:
            logger.info("Idempotent skip: Hotwash feedback already persisted")
            if hasattr(chunk, 'metadata') and chunk.metadata:
                feedback_ids = chunk.metadata.get('feedback_item_ids', [])
                if feedback_ids:
                    return list(await SimulationFeedback.objects.filter(
                        id__in=feedback_ids
                    ).ato_list())
            return []

        # Validate data if it's a dict
        if isinstance(data, dict):
            data = self.schema.model_validate(data)

        # Persist feedback items
        feedback_items = await self._persist_feedback_block(
            data.metadata, simulation_id
        )

        logger.info(
            f"Persisted {len(feedback_items)} hotwash feedback items for simulation {simulation_id}"
        )

        # Link to idempotency tracker
        if feedback_items:
            chunk.metadata = {
                "feedback_item_ids": [item.id for item in feedback_items],
                "count": len(feedback_items),
            }
            chunk.content_type = await ContentType.objects.aget_for_model(
                SimulationFeedback
            )
            chunk.object_id = feedback_items[0].id
            await chunk.asave()

        return feedback_items

    async def _persist_feedback_block(
        self, feedback_block, simulation_id: int
    ) -> list:
        """Persist HotwashInitialBlock to SimulationFeedback records."""
        feedback_items = []

        feedback_mapping = [
            ("hotwash_correct_diagnosis", str(feedback_block.correct_diagnosis)),
            ("hotwash_correct_treatment_plan", str(feedback_block.correct_treatment_plan)),
            ("hotwash_patient_experience", str(feedback_block.patient_experience)),
            ("hotwash_overall_feedback", feedback_block.overall_feedback),
        ]

        for key, value in feedback_mapping:
            try:
                feedback_obj, created = await SimulationFeedback.objects.aupdate_or_create(
                    simulation_id=simulation_id,
                    key=key,
                    defaults={"value": value},
                )
                feedback_items.append(feedback_obj)

            except Exception as exc:
                logger.warning(f"Failed to persist feedback item: {exc}", exc_info=True)

        return feedback_items
