"""Phase-1 model tests for the assessments app.

Covers constraints, validation, and immutability rules for
AssessmentRubric, AssessmentCriterion, Assessment,
AssessmentCriterionScore, and AssessmentSource.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
import pytest

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# AssessmentRubric
# ---------------------------------------------------------------------------


def test_rubric_global_unique_slug_version(account):
    from apps.assessments.models import AssessmentRubric

    AssessmentRubric.objects.create(
        slug="rubric-a",
        name="Rubric A v1",
        scope=AssessmentRubric.Scope.GLOBAL,
        assessment_type="initial_feedback",
        version=1,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        AssessmentRubric.objects.create(
            slug="rubric-a",
            name="Rubric A v1 dup",
            scope=AssessmentRubric.Scope.GLOBAL,
            assessment_type="initial_feedback",
            version=1,
        )
    AssessmentRubric.objects.create(
        slug="rubric-a",
        name="Rubric A v2",
        scope=AssessmentRubric.Scope.GLOBAL,
        assessment_type="initial_feedback",
        version=2,
    )


def test_rubric_account_unique_slug_version(account, account_b):
    from apps.assessments.models import AssessmentRubric

    AssessmentRubric.objects.create(
        slug="custom",
        name="Custom v1 A",
        scope=AssessmentRubric.Scope.ACCOUNT,
        account=account,
        assessment_type="initial_feedback",
        version=1,
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        AssessmentRubric.objects.create(
            slug="custom",
            name="Custom v1 A dup",
            scope=AssessmentRubric.Scope.ACCOUNT,
            account=account,
            assessment_type="initial_feedback",
            version=1,
        )
    # Same slug+version on a different account is fine.
    AssessmentRubric.objects.create(
        slug="custom",
        name="Custom v1 B",
        scope=AssessmentRubric.Scope.ACCOUNT,
        account=account_b,
        assessment_type="initial_feedback",
        version=1,
    )


def test_rubric_account_required_when_scope_account(account):
    from apps.assessments.models import AssessmentRubric

    with pytest.raises(ValidationError):
        AssessmentRubric.objects.create(
            slug="x",
            name="x",
            scope=AssessmentRubric.Scope.ACCOUNT,
            account=None,
            assessment_type="initial_feedback",
        )


def test_rubric_account_forbidden_when_scope_global(account):
    from apps.assessments.models import AssessmentRubric

    with pytest.raises(ValidationError):
        AssessmentRubric.objects.create(
            slug="y",
            name="y",
            scope=AssessmentRubric.Scope.GLOBAL,
            account=account,
            assessment_type="initial_feedback",
        )


def test_published_rubric_locked_fields_immutable(published_rubric):
    published_rubric.name = "New Name"
    with pytest.raises(ValidationError):
        published_rubric.save()


def test_published_rubric_can_archive(published_rubric):
    from apps.assessments.models import AssessmentRubric

    published_at = published_rubric.published_at
    assert published_at is not None
    published_rubric.status = AssessmentRubric.Status.ARCHIVED
    published_rubric.save()
    published_rubric.refresh_from_db()
    assert published_rubric.status == AssessmentRubric.Status.ARCHIVED
    assert published_rubric.published_at == published_at


def test_published_rubric_cannot_revert_to_draft(published_rubric):
    from apps.assessments.models import AssessmentRubric

    published_rubric.status = AssessmentRubric.Status.DRAFT
    with pytest.raises(ValidationError):
        published_rubric.save()


def test_published_at_auto_set_on_publish(draft_rubric):
    from apps.assessments.models import AssessmentRubric

    assert draft_rubric.published_at is None
    draft_rubric.status = AssessmentRubric.Status.PUBLISHED
    draft_rubric.save()
    draft_rubric.refresh_from_db()
    assert draft_rubric.published_at is not None


# ---------------------------------------------------------------------------
# AssessmentCriterion
# ---------------------------------------------------------------------------


def test_criterion_unique_slug_per_rubric(draft_rubric):
    from apps.assessments.models import AssessmentCriterion

    with pytest.raises(IntegrityError), transaction.atomic():
        AssessmentCriterion.objects.create(
            rubric=draft_rubric,
            slug="correct_diagnosis",
            label="dup",
            value_type=AssessmentCriterion.ValueType.BOOL,
        )


def test_criterion_enum_requires_allowed_values(draft_rubric):
    from apps.assessments.models import AssessmentCriterion

    with pytest.raises(ValidationError):
        AssessmentCriterion.objects.create(
            rubric=draft_rubric,
            slug="bad_enum",
            label="Bad enum",
            value_type=AssessmentCriterion.ValueType.ENUM,
            allowed_values=[],
        )


def test_criterion_min_max_only_on_numeric(draft_rubric):
    from apps.assessments.models import AssessmentCriterion

    with pytest.raises(ValidationError):
        AssessmentCriterion.objects.create(
            rubric=draft_rubric,
            slug="bad_text",
            label="Bad text",
            value_type=AssessmentCriterion.ValueType.TEXT,
            min_value=Decimal("0"),
        )


def test_criterion_min_le_max(draft_rubric):
    from apps.assessments.models import AssessmentCriterion

    with pytest.raises(ValidationError):
        AssessmentCriterion.objects.create(
            rubric=draft_rubric,
            slug="bad_range",
            label="Bad range",
            value_type=AssessmentCriterion.ValueType.INT,
            min_value=Decimal("5"),
            max_value=Decimal("3"),
        )


def test_criterion_locked_when_rubric_published(published_rubric):
    from apps.assessments.models import AssessmentCriterion

    with pytest.raises(ValidationError):
        AssessmentCriterion.objects.create(
            rubric=published_rubric,
            slug="late_addition",
            label="Late addition",
            value_type=AssessmentCriterion.ValueType.BOOL,
        )


def test_criterion_allowed_values_forbidden_for_non_enum(draft_rubric):
    from apps.assessments.models import AssessmentCriterion

    with pytest.raises(ValidationError):
        AssessmentCriterion.objects.create(
            rubric=draft_rubric,
            slug="weird",
            label="Weird",
            value_type=AssessmentCriterion.ValueType.BOOL,
            allowed_values=["a", "b"],
        )


# ---------------------------------------------------------------------------
# Assessment + AssessmentCriterionScore
# ---------------------------------------------------------------------------


def _make_assessment(rubric, account, user):
    from apps.assessments.models import Assessment

    return Assessment.objects.create(
        rubric=rubric,
        account=account,
        assessed_user=user,
        assessment_type="initial_feedback",
        lab_type="chatlab",
    )


def test_assessment_overall_score_constraint_blocks_out_of_range(published_rubric, account, user):
    """Bypass clean() to verify the DB-level CheckConstraint."""
    from apps.assessments.models import Assessment

    a = Assessment(
        rubric=published_rubric,
        account=account,
        assessed_user=user,
        assessment_type="initial_feedback",
        lab_type="chatlab",
        overall_score=Decimal("1.500"),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        super(Assessment, a).save()


def test_score_value_field_must_match_value_type(published_rubric, account, user):
    from apps.assessments.models import AssessmentCriterionScore

    assessment = _make_assessment(published_rubric, account, user)
    bool_criterion = published_rubric.criteria.get(slug="correct_diagnosis")
    with pytest.raises(ValidationError):
        AssessmentCriterionScore.objects.create(
            assessment=assessment,
            criterion=bool_criterion,
            value_int=1,  # wrong field for BOOL
        )


def test_score_int_range_enforced(published_rubric, account, user):
    from apps.assessments.models import AssessmentCriterionScore

    assessment = _make_assessment(published_rubric, account, user)
    int_criterion = published_rubric.criteria.get(slug="patient_experience")
    with pytest.raises(ValidationError):
        AssessmentCriterionScore.objects.create(
            assessment=assessment,
            criterion=int_criterion,
            value_int=6,  # max is 5
        )


def test_score_enum_must_be_in_allowed_values(published_rubric, account, user):
    from apps.assessments.models import AssessmentCriterionScore

    assessment = _make_assessment(published_rubric, account, user)
    enum_criterion = published_rubric.criteria.get(slug="acuity")
    with pytest.raises(ValidationError):
        AssessmentCriterionScore.objects.create(
            assessment=assessment,
            criterion=enum_criterion,
            value_text="extreme",  # not in allowed_values
        )


def test_score_rubric_mismatch_rejected(published_rubric, account, user):
    """A score whose criterion belongs to a different rubric is rejected."""
    from apps.assessments.models import (
        AssessmentCriterion,
        AssessmentCriterionScore,
        AssessmentRubric,
    )

    other_rubric = AssessmentRubric.objects.create(
        slug="other-rubric",
        name="Other",
        scope=AssessmentRubric.Scope.GLOBAL,
        assessment_type="something_else",
        version=1,
    )
    other_criterion = AssessmentCriterion.objects.create(
        rubric=other_rubric,
        slug="x",
        label="X",
        value_type=AssessmentCriterion.ValueType.BOOL,
    )
    assessment = _make_assessment(published_rubric, account, user)
    with pytest.raises(ValidationError):
        AssessmentCriterionScore.objects.create(
            assessment=assessment,
            criterion=other_criterion,
            value_bool=True,
        )


def test_score_unique_per_assessment_criterion(published_rubric, account, user):
    from apps.assessments.models import AssessmentCriterionScore

    assessment = _make_assessment(published_rubric, account, user)
    bool_criterion = published_rubric.criteria.get(slug="correct_diagnosis")
    AssessmentCriterionScore.objects.create(
        assessment=assessment,
        criterion=bool_criterion,
        value_bool=True,
        score=Decimal("1.000"),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        AssessmentCriterionScore.objects.create(
            assessment=assessment,
            criterion=bool_criterion,
            value_bool=False,
            score=Decimal("0.000"),
        )


def test_score_check_constraint_blocks_out_of_range(published_rubric, account, user):
    from apps.assessments.models import AssessmentCriterionScore

    assessment = _make_assessment(published_rubric, account, user)
    bool_criterion = published_rubric.criteria.get(slug="correct_diagnosis")
    cs = AssessmentCriterionScore(
        assessment=assessment,
        criterion=bool_criterion,
        value_bool=True,
        score=Decimal("1.500"),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        super(AssessmentCriterionScore, cs).save()


def test_score_typed_value_round_trip(published_rubric, account, user):
    from apps.assessments.models import AssessmentCriterionScore

    assessment = _make_assessment(published_rubric, account, user)
    bool_criterion = published_rubric.criteria.get(slug="correct_diagnosis")
    int_criterion = published_rubric.criteria.get(slug="patient_experience")

    cs_bool = AssessmentCriterionScore.objects.create(
        assessment=assessment,
        criterion=bool_criterion,
        value_bool=True,
        score=Decimal("1.000"),
    )
    cs_int = AssessmentCriterionScore.objects.create(
        assessment=assessment,
        criterion=int_criterion,
        value_int=4,
        score=Decimal("0.800"),
    )
    cs_bool.refresh_from_db()
    cs_int.refresh_from_db()
    assert cs_bool.value_bool is True
    assert cs_bool.value_int is None
    assert cs_int.value_int == 4
    assert cs_int.value_bool is None


# ---------------------------------------------------------------------------
# AssessmentSource
# ---------------------------------------------------------------------------


def test_source_simulation_requires_simulation_fk(published_rubric, account, user, simulation):
    from apps.assessments.models import AssessmentSource

    assessment = _make_assessment(published_rubric, account, user)
    with pytest.raises(ValidationError):
        AssessmentSource.objects.create(
            assessment=assessment,
            source_type=AssessmentSource.SourceType.SIMULATION,
        )


def test_source_assessment_requires_source_assessment_fk(published_rubric, account, user):
    from apps.assessments.models import AssessmentSource

    assessment = _make_assessment(published_rubric, account, user)
    with pytest.raises(ValidationError):
        AssessmentSource.objects.create(
            assessment=assessment,
            source_type=AssessmentSource.SourceType.ASSESSMENT,
        )


def test_source_simulation_must_not_set_source_assessment(
    published_rubric, account, user, simulation
):
    from apps.assessments.models import AssessmentSource

    assessment = _make_assessment(published_rubric, account, user)
    other = _make_assessment(published_rubric, account, user)
    with pytest.raises(ValidationError):
        AssessmentSource.objects.create(
            assessment=assessment,
            source_type=AssessmentSource.SourceType.SIMULATION,
            simulation=simulation,
            source_assessment=other,
        )


def test_source_no_self_reference(published_rubric, account, user):
    from apps.assessments.models import AssessmentSource

    assessment = _make_assessment(published_rubric, account, user)
    with pytest.raises(ValidationError):
        AssessmentSource.objects.create(
            assessment=assessment,
            source_type=AssessmentSource.SourceType.ASSESSMENT,
            source_assessment=assessment,
        )


def test_source_unique_primary_per_assessment(published_rubric, account, user, simulation):
    from apps.assessments.models import AssessmentSource

    assessment = _make_assessment(published_rubric, account, user)
    AssessmentSource.objects.create(
        assessment=assessment,
        source_type=AssessmentSource.SourceType.SIMULATION,
        role=AssessmentSource.Role.PRIMARY,
        simulation=simulation,
    )
    other_sim_source = _make_assessment(published_rubric, account, user)
    with pytest.raises(IntegrityError), transaction.atomic():
        # Use raw SQL bypass via super().save() to skip clean() (which
        # would raise ValidationError instead of letting the unique
        # constraint do the work).
        second = AssessmentSource(
            assessment=assessment,
            source_type=AssessmentSource.SourceType.ASSESSMENT,
            role=AssessmentSource.Role.PRIMARY,
            source_assessment=other_sim_source,
        )
        super(AssessmentSource, second).save()


def test_source_multiple_non_primary_roles_allowed(published_rubric, account, user, simulation):
    from apps.assessments.models import AssessmentSource

    assessment = _make_assessment(published_rubric, account, user)
    AssessmentSource.objects.create(
        assessment=assessment,
        source_type=AssessmentSource.SourceType.SIMULATION,
        role=AssessmentSource.Role.PRIMARY,
        simulation=simulation,
    )
    parent = _make_assessment(published_rubric, account, user)
    AssessmentSource.objects.create(
        assessment=assessment,
        source_type=AssessmentSource.SourceType.ASSESSMENT,
        role=AssessmentSource.Role.GENERATED_FROM,
        source_assessment=parent,
    )
    assert assessment.sources.count() == 2
