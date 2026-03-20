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
    from asgiref.sync import sync_to_async

    from apps.simcore.models import Simulation, SimulationFeedback, SimulationSummary

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

    try:
        simulation = await Simulation.objects.aget(pk=ctx.simulation_id)
        summary_text = str(block.overall_feedback)
        await sync_to_async(SimulationSummary.objects.update_or_create)(
            simulation=simulation,
            defaults={
                "summary_text": summary_text,
                "chief_complaint": simulation.chief_complaint or "",
                "diagnosis": simulation.diagnosis or "",
                "strengths": [str(block.correct_treatment_plan)],
                "improvement_areas": [str(block.correct_diagnosis)],
                "learning_points": [str(block.patient_experience)],
                "recommended_study_topics": [],
            },
        )
    except Exception as exc:
        logger.warning("Failed to persist simulation summary: %s", exc, exc_info=True)

    return created


async def persist_continuation_feedback_block(block, ctx: PersistContext) -> list:
    """Persist continuation feedback block for learner follow-up Q&A."""
    from apps.simcore.models import SimulationFeedback

    try:
        obj, _ = await SimulationFeedback.objects.aupdate_or_create(
            simulation_id=ctx.simulation_id,
            key="hotwash_continuation_direct_answer",
            defaults={"value": block.direct_answer},
        )
    except Exception as exc:
        logger.warning("Failed to persist continuation feedback item: %s", exc, exc_info=True)
        return []

    return [obj]
