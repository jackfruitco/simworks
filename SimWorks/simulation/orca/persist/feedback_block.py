"""Persist functions for simulation schemas.

These functions handle complex transformations where Pydantic output items
do not map 1:1 to Django model fields.
"""
import logging

from orchestrai_django.persistence import PersistContext

logger = logging.getLogger(__name__)


async def persist_initial_feedback_block(block, ctx: PersistContext) -> list:
    """Persist InitialFeedbackBlock → multiple SimulationFeedback records.

    This is an explicit persist function because one Pydantic model
    (InitialFeedbackBlock) maps to multiple Django instances (one
    SimulationFeedback per field).
    """
    from simulation.models import SimulationFeedback

    mapping = [
        ("hotwash_correct_diagnosis", str(block.correct_diagnosis)),
        ("hotwash_correct_treatment_plan", str(block.correct_treatment_plan)),
        ("hotwash_patient_experience", str(block.patient_experience)),
        ("hotwash_overall_feedback", block.overall_feedback),
    ]

    created = []
    for key, value in mapping:
        try:
            obj, _ = await SimulationFeedback.objects.aupdate_or_create(
                simulation_id=ctx.simulation_id,
                key=key,
                defaults={"value": value},
            )
            created.append(obj)
        except Exception as exc:
            logger.warning("Failed to persist feedback item: %s", exc, exc_info=True)

    return created
