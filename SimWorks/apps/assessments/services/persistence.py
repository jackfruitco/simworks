"""Persistence functions for the orca initial-feedback and continuation flows.

Function names mirror the legacy ``apps.simcore.orca.persist.feedback_block``
module so that the orca declarative ``__persist__`` dict can be repointed
purely by changing the import path. Behavior, however, is entirely new:
these write to :class:`Assessment` /
:class:`AssessmentCriterionScore` / :class:`AssessmentSource` and update
:class:`SimulationSummary` with typed values (no ``str()`` wrapping).
"""

from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.db import transaction

logger = logging.getLogger(__name__)


# Slug → block-attribute mapping for the chatlab initial-feedback rubric.
# Keyed by criterion slug so adding criteria to the YAML only requires
# extending this dict.
_INITIAL_VALUE_BY_SLUG = {
    "correct_diagnosis": ("correct_diagnosis", "value_bool"),
    "correct_treatment_plan": ("correct_treatment_plan", "value_bool"),
    "patient_experience": ("patient_experience", "value_int"),
}


# ---------------------------------------------------------------------------
# Initial feedback
# ---------------------------------------------------------------------------


async def persist_initial_feedback_block(block, ctx) -> list:
    """Persist an :class:`InitialFeedbackBlock` to the assessments app.

    Returns a one-element list ``[assessment]`` (the orca runtime passes
    this to ``post_persist`` which broadcasts an
    ``assessment.item.created`` event).
    """
    from apps.simcore.models import Simulation

    simulation_id = ctx.simulation_id
    service_call_attempt_id = (getattr(ctx, "extra", {}) or {}).get("service_call_attempt_id")

    try:
        sim = await Simulation.objects.select_related("account", "user").aget(pk=simulation_id)
    except Simulation.DoesNotExist:
        logger.warning(
            "[assessments] simulation %s not found; skipping persist.",
            simulation_id,
        )
        return []

    try:
        assessment = await sync_to_async(_write_initial_assessment)(
            sim=sim,
            block=block,
            service_call_attempt_id=service_call_attempt_id,
        )
    except Exception as exc:
        logger.warning(
            "[assessments] persist_initial_feedback_block failed for sim=%s: %s",
            simulation_id,
            exc,
            exc_info=True,
        )
        return []

    if assessment is None:
        return []
    return [assessment]


def _write_initial_assessment(*, sim, block, service_call_attempt_id):
    from apps.assessments.models import (
        Assessment,
        AssessmentCriterionScore,
        AssessmentSource,
    )
    from apps.assessments.services import (
        RubricNotFoundError,
        compute_overall_score,
        normalize_criterion_value,
        resolve_rubric,
    )
    from apps.simcore.models import SimulationSummary

    try:
        rubric = resolve_rubric(
            account=sim.account,
            lab_type="chatlab",
            assessment_type="initial_feedback",
        )
    except RubricNotFoundError:
        logger.warning(
            "[assessments] no rubric for sim=%s lab=chatlab type=initial_feedback",
            sim.pk,
        )
        return None

    with transaction.atomic():
        assessment = Assessment.objects.create(
            rubric=rubric,
            account=sim.account,
            assessed_user=sim.user,
            assessment_type="initial_feedback",
            lab_type="chatlab",
            overall_summary=block.overall_feedback,
            generated_by_service="GenerateInitialFeedback",
            source_attempt_id=service_call_attempt_id,
        )

        for criterion in rubric.criteria.all().order_by("sort_order"):
            mapping = _INITIAL_VALUE_BY_SLUG.get(criterion.slug)
            if mapping is None:
                logger.warning(
                    "[assessments] criterion slug %r not in initial value map",
                    criterion.slug,
                )
                continue
            attr, value_field = mapping
            raw_value = getattr(block, attr)

            kwargs = {value_field: raw_value}
            kwargs["score"] = normalize_criterion_value(criterion, **kwargs)
            AssessmentCriterionScore.objects.create(
                assessment=assessment,
                criterion=criterion,
                **kwargs,
            )

        # Refresh + compute overall.
        scored = list(assessment.criterion_scores.select_related("criterion").all())
        assessment.overall_score = compute_overall_score(scored)
        assessment.save(update_fields=["overall_score"])

        AssessmentSource.objects.create(
            assessment=assessment,
            source_type=AssessmentSource.SourceType.SIMULATION,
            role=AssessmentSource.Role.PRIMARY,
            simulation=sim,
        )

        # Update SimulationSummary with typed values.
        SimulationSummary.objects.update_or_create(
            simulation=sim,
            defaults={
                "summary_text": block.overall_feedback,
                "chief_complaint": sim.chief_complaint or "",
                "diagnosis": sim.diagnosis or "",
                "strengths": (
                    ["Treatment plan was appropriate."] if block.correct_treatment_plan else []
                ),
                "improvement_areas": (
                    [] if block.correct_diagnosis else ["Diagnosis was incorrect or missed."]
                ),
                "learning_points": [f"Patient experience rated {block.patient_experience}/5."],
                "recommended_study_topics": [],
            },
        )

    return assessment


# ---------------------------------------------------------------------------
# Continuation Q&A
# ---------------------------------------------------------------------------


async def persist_continuation_feedback_block(block, ctx) -> list:
    """Persist a :class:`FeedbackContinuationBlock` as a separate Assessment.

    The continuation creates a new Assessment of
    ``assessment_type="continuation_feedback"`` linked to the simulation
    via a ``primary`` :class:`AssessmentSource` and (when the prior
    initial assessment exists) to that initial assessment via a
    ``generated_from`` source row.
    """
    from apps.simcore.models import Simulation

    simulation_id = ctx.simulation_id
    service_call_attempt_id = (getattr(ctx, "extra", {}) or {}).get("service_call_attempt_id")

    try:
        sim = await Simulation.objects.select_related("account", "user").aget(pk=simulation_id)
    except Simulation.DoesNotExist:
        logger.warning(
            "[assessments] simulation %s not found; skipping continuation.",
            simulation_id,
        )
        return []

    try:
        assessment = await sync_to_async(_write_continuation_assessment)(
            sim=sim,
            block=block,
            service_call_attempt_id=service_call_attempt_id,
        )
    except Exception as exc:
        logger.warning(
            "[assessments] persist_continuation_feedback_block failed for sim=%s: %s",
            simulation_id,
            exc,
            exc_info=True,
        )
        return []

    if assessment is None:
        return []
    return [assessment]


def _write_continuation_assessment(*, sim, block, service_call_attempt_id):
    from apps.assessments.models import (
        Assessment,
        AssessmentCriterionScore,
        AssessmentSource,
    )
    from apps.assessments.services import RubricNotFoundError, resolve_rubric

    try:
        rubric = resolve_rubric(
            account=sim.account,
            lab_type="chatlab",
            assessment_type="continuation_feedback",
        )
    except RubricNotFoundError:
        logger.warning(
            "[assessments] no rubric for sim=%s lab=chatlab type=continuation_feedback",
            sim.pk,
        )
        return None

    with transaction.atomic():
        parent = (
            Assessment.objects.filter(
                sources__simulation=sim,
                sources__role=AssessmentSource.Role.PRIMARY,
                sources__source_type=AssessmentSource.SourceType.SIMULATION,
                assessment_type="initial_feedback",
            )
            .order_by("-created_at")
            .first()
        )

        assessment = Assessment.objects.create(
            rubric=rubric,
            account=sim.account,
            assessed_user=sim.user,
            assessment_type="continuation_feedback",
            lab_type="chatlab",
            overall_summary=block.direct_answer,
            generated_by_service="GenerateFeedbackContinuationReply",
            source_attempt_id=service_call_attempt_id,
        )

        # Single text criterion for the continuation rubric.
        direct_answer_criterion = rubric.criteria.get(slug="direct_answer")
        AssessmentCriterionScore.objects.create(
            assessment=assessment,
            criterion=direct_answer_criterion,
            value_text=block.direct_answer,
            score=None,
        )

        AssessmentSource.objects.create(
            assessment=assessment,
            source_type=AssessmentSource.SourceType.SIMULATION,
            role=AssessmentSource.Role.PRIMARY,
            simulation=sim,
        )
        if parent is not None:
            AssessmentSource.objects.create(
                assessment=assessment,
                source_type=AssessmentSource.SourceType.ASSESSMENT,
                role=AssessmentSource.Role.GENERATED_FROM,
                source_assessment=parent,
            )

    return assessment
