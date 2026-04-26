"""Direct tests for the assessments persistence service.

These exercise the synchronous inner functions
(``_write_initial_assessment``, ``_write_continuation_assessment``) so we
can assert behaviour without needing to spin up the async orca pipeline.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.django_db


def _block(**overrides):
    """Lightweight stand-in for :class:`InitialFeedbackBlock`."""
    base = {
        "correct_diagnosis": True,
        "correct_treatment_plan": True,
        "patient_experience": 4,
        "overall_feedback": "Good work.",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _seed_continuation_rubric():
    from apps.assessments.models import AssessmentCriterion, AssessmentRubric

    rubric = AssessmentRubric.objects.create(
        slug="chatlab_continuation_feedback",
        name="ChatLab Continuation Feedback",
        scope=AssessmentRubric.Scope.GLOBAL,
        lab_type="chatlab",
        assessment_type="continuation_feedback",
        version=1,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    AssessmentCriterion.objects.create(
        rubric=rubric,
        slug="direct_answer",
        label="Direct Answer",
        category="communication",
        value_type=AssessmentCriterion.ValueType.TEXT,
        sort_order=10,
    )
    return rubric


def _seed_initial_rubric():
    """Mirror the chatlab YAML shape but stamp PUBLISHED with three criteria."""
    from apps.assessments.models import AssessmentCriterion, AssessmentRubric

    rubric = AssessmentRubric.objects.create(
        slug="chatlab_initial_feedback",
        name="ChatLab Initial Feedback",
        scope=AssessmentRubric.Scope.GLOBAL,
        lab_type="chatlab",
        assessment_type="initial_feedback",
        version=1,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    AssessmentCriterion.objects.create(
        rubric=rubric,
        slug="correct_diagnosis",
        label="Correct Diagnosis",
        category="clinical_reasoning",
        value_type=AssessmentCriterion.ValueType.BOOL,
        sort_order=10,
    )
    AssessmentCriterion.objects.create(
        rubric=rubric,
        slug="correct_treatment_plan",
        label="Correct Treatment Plan",
        category="treatment",
        value_type=AssessmentCriterion.ValueType.BOOL,
        sort_order=20,
    )
    AssessmentCriterion.objects.create(
        rubric=rubric,
        slug="patient_experience",
        label="Patient Experience",
        category="communication",
        value_type=AssessmentCriterion.ValueType.INT,
        min_value=Decimal("0"),
        max_value=Decimal("5"),
        sort_order=30,
    )
    return rubric


# ---------------------------------------------------------------------------
# Initial assessment
# ---------------------------------------------------------------------------


def test_initial_creates_assessment_and_typed_scores(simulation):
    from apps.assessments.models import Assessment, AssessmentCriterionScore
    from apps.assessments.services.persistence import _write_initial_assessment

    _seed_initial_rubric()

    assessment = _write_initial_assessment(
        sim=simulation,
        block=_block(),
        service_call_attempt_id=None,
    )
    assert isinstance(assessment, Assessment)

    scores = AssessmentCriterionScore.objects.filter(assessment=assessment)
    slugs = sorted(scores.values_list("criterion__slug", flat=True))
    assert slugs == [
        "correct_diagnosis",
        "correct_treatment_plan",
        "patient_experience",
    ]

    diag = scores.get(criterion__slug="correct_diagnosis")
    assert diag.value_bool is True
    assert diag.value_int is None
    assert diag.score == Decimal("1.000")

    plan = scores.get(criterion__slug="correct_treatment_plan")
    assert plan.value_bool is True
    assert plan.score == Decimal("1.000")

    exp = scores.get(criterion__slug="patient_experience")
    assert exp.value_int == 4
    assert exp.value_bool is None
    assert exp.score == Decimal("0.800")


def test_initial_overall_score_is_weighted_mean(simulation):
    from apps.assessments.services.persistence import _write_initial_assessment

    _seed_initial_rubric()

    assessment = _write_initial_assessment(
        sim=simulation,
        block=_block(
            correct_diagnosis=True,
            correct_treatment_plan=True,
            patient_experience=4,
        ),
        service_call_attempt_id=None,
    )
    # (1.0 + 1.0 + 0.8) / 3 = 0.933
    assert assessment.overall_score == Decimal("0.933")


def test_initial_creates_primary_simulation_source(simulation):
    from apps.assessments.models import AssessmentSource
    from apps.assessments.services.persistence import _write_initial_assessment

    _seed_initial_rubric()

    assessment = _write_initial_assessment(
        sim=simulation, block=_block(), service_call_attempt_id=None
    )

    sources = AssessmentSource.objects.filter(assessment=assessment)
    assert sources.count() == 1
    src = sources.get()
    assert src.role == AssessmentSource.Role.PRIMARY
    assert src.source_type == AssessmentSource.SourceType.SIMULATION
    assert src.simulation_id == simulation.id


def test_initial_overall_summary_set_from_block(simulation):
    from apps.assessments.services.persistence import _write_initial_assessment

    _seed_initial_rubric()

    assessment = _write_initial_assessment(
        sim=simulation,
        block=_block(overall_feedback="Excellent communication."),
        service_call_attempt_id=None,
    )
    assert assessment.overall_summary == "Excellent communication."


def test_initial_simulation_summary_uses_typed_values(simulation):
    from apps.assessments.services.persistence import _write_initial_assessment
    from apps.simcore.models import SimulationSummary

    _seed_initial_rubric()

    _write_initial_assessment(
        sim=simulation,
        block=_block(
            correct_diagnosis=False,
            correct_treatment_plan=True,
            patient_experience=3,
            overall_feedback="Workable.",
        ),
        service_call_attempt_id=None,
    )

    summary = SimulationSummary.objects.get(simulation=simulation)
    assert summary.summary_text == "Workable."
    # Typed sentences, not "True"/"False" string round-trips.
    assert summary.strengths == ["Treatment plan was appropriate."]
    assert summary.improvement_areas == ["Diagnosis was incorrect or missed."]
    assert summary.learning_points == ["Patient experience rated 3/5."]


def test_legacy_simulation_feedback_class_is_gone():
    """Phase 5 removed the SimulationFeedback polymorphic subclass."""
    import apps.simcore.models as simcore_models

    assert not hasattr(simcore_models, "SimulationFeedback")


def test_initial_returns_none_when_rubric_missing(simulation):
    from apps.assessments.services.persistence import _write_initial_assessment

    # No rubric seeded → resolver raises → function returns None.
    result = _write_initial_assessment(sim=simulation, block=_block(), service_call_attempt_id=None)
    assert result is None


# ---------------------------------------------------------------------------
# Continuation
# ---------------------------------------------------------------------------


def test_continuation_creates_separate_assessment_with_two_sources(simulation):
    from apps.assessments.models import (
        Assessment,
        AssessmentCriterionScore,
        AssessmentSource,
    )
    from apps.assessments.services.persistence import (
        _write_continuation_assessment,
        _write_initial_assessment,
    )

    _seed_initial_rubric()
    _seed_continuation_rubric()

    initial = _write_initial_assessment(
        sim=simulation, block=_block(), service_call_attempt_id=None
    )
    continuation = _write_continuation_assessment(
        sim=simulation,
        block=SimpleNamespace(direct_answer="Prioritize ABCs."),
        service_call_attempt_id=None,
    )

    assert continuation.id != initial.id
    assert continuation.assessment_type == "continuation_feedback"
    assert continuation.overall_summary == "Prioritize ABCs."

    # Single text criterion score on the continuation.
    scores = AssessmentCriterionScore.objects.filter(assessment=continuation)
    assert scores.count() == 1
    only = scores.get()
    assert only.criterion.slug == "direct_answer"
    assert only.value_text == "Prioritize ABCs."
    assert only.value_bool is None
    assert only.value_int is None

    # Two sources: simulation/primary + assessment/generated_from.
    sources = AssessmentSource.objects.filter(assessment=continuation)
    assert sources.count() == 2
    primary = sources.get(role=AssessmentSource.Role.PRIMARY)
    assert primary.source_type == AssessmentSource.SourceType.SIMULATION
    assert primary.simulation_id == simulation.id

    parent_link = sources.get(role=AssessmentSource.Role.GENERATED_FROM)
    assert parent_link.source_type == AssessmentSource.SourceType.ASSESSMENT
    assert parent_link.source_assessment_id == initial.id

    # Two distinct Assessment rows now exist for this simulation.
    assert Assessment.objects.filter(sources__simulation=simulation).distinct().count() == 2


def test_continuation_without_prior_initial_still_creates(simulation):
    from apps.assessments.models import AssessmentSource
    from apps.assessments.services.persistence import _write_continuation_assessment

    _seed_continuation_rubric()

    continuation = _write_continuation_assessment(
        sim=simulation,
        block=SimpleNamespace(direct_answer="Workup with labs."),
        service_call_attempt_id=None,
    )
    sources = AssessmentSource.objects.filter(assessment=continuation)
    assert sources.count() == 1
    only = sources.get()
    assert only.role == AssessmentSource.Role.PRIMARY
    assert only.source_type == AssessmentSource.SourceType.SIMULATION


def test_continuation_returns_none_when_rubric_missing(simulation):
    from apps.assessments.services.persistence import _write_continuation_assessment

    result = _write_continuation_assessment(
        sim=simulation,
        block=SimpleNamespace(direct_answer="anything"),
        service_call_attempt_id=None,
    )
    assert result is None
