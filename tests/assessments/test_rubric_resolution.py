"""Resolver tests: account-priority, version-priority, status filtering."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db


def _make_rubric(
    *,
    slug,
    version,
    scope,
    status,
    account=None,
    lab_type="chatlab",
    assessment_type="initial_feedback",
):
    from apps.assessments.models import AssessmentRubric

    return AssessmentRubric.objects.create(
        slug=slug,
        name=f"{slug} v{version}",
        scope=scope,
        account=account,
        lab_type=lab_type,
        assessment_type=assessment_type,
        version=version,
        status=status,
    )


def test_resolves_global_published_rubric():
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import resolve_rubric

    _make_rubric(
        slug="r",
        version=1,
        scope=AssessmentRubric.Scope.GLOBAL,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    result = resolve_rubric(account=None, lab_type="chatlab", assessment_type="initial_feedback")
    assert result.slug == "r"


def test_prefers_account_scoped_over_global(account):
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import resolve_rubric

    _make_rubric(
        slug="r",
        version=1,
        scope=AssessmentRubric.Scope.GLOBAL,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    custom = _make_rubric(
        slug="r-acct",
        version=1,
        scope=AssessmentRubric.Scope.ACCOUNT,
        account=account,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    result = resolve_rubric(account=account, lab_type="chatlab", assessment_type="initial_feedback")
    assert result.pk == custom.pk


def test_falls_back_to_global_when_account_has_no_rubric(account, account_b):
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import resolve_rubric

    _make_rubric(
        slug="g",
        version=1,
        scope=AssessmentRubric.Scope.GLOBAL,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    _make_rubric(
        slug="a-only",
        version=1,
        scope=AssessmentRubric.Scope.ACCOUNT,
        account=account,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    result = resolve_rubric(
        account=account_b, lab_type="chatlab", assessment_type="initial_feedback"
    )
    assert result.slug == "g"


def test_higher_version_wins_among_global():
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import resolve_rubric

    _make_rubric(
        slug="r",
        version=1,
        scope=AssessmentRubric.Scope.GLOBAL,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    v2 = _make_rubric(
        slug="r",
        version=2,
        scope=AssessmentRubric.Scope.GLOBAL,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    result = resolve_rubric(account=None, lab_type="chatlab", assessment_type="initial_feedback")
    assert result.pk == v2.pk


def test_higher_version_wins_among_account_scoped(account):
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import resolve_rubric

    _make_rubric(
        slug="r",
        version=1,
        scope=AssessmentRubric.Scope.ACCOUNT,
        account=account,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    v2 = _make_rubric(
        slug="r",
        version=2,
        scope=AssessmentRubric.Scope.ACCOUNT,
        account=account,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    result = resolve_rubric(account=account, lab_type="chatlab", assessment_type="initial_feedback")
    assert result.pk == v2.pk


def test_ignores_draft_rubrics():
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import RubricNotFoundError, resolve_rubric

    _make_rubric(
        slug="r",
        version=1,
        scope=AssessmentRubric.Scope.GLOBAL,
        status=AssessmentRubric.Status.DRAFT,
    )
    with pytest.raises(RubricNotFoundError):
        resolve_rubric(account=None, lab_type="chatlab", assessment_type="initial_feedback")


def test_ignores_archived_rubrics():
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import RubricNotFoundError, resolve_rubric

    rubric = _make_rubric(
        slug="r",
        version=1,
        scope=AssessmentRubric.Scope.GLOBAL,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    rubric.status = AssessmentRubric.Status.ARCHIVED
    rubric.save()
    with pytest.raises(RubricNotFoundError):
        resolve_rubric(account=None, lab_type="chatlab", assessment_type="initial_feedback")


def test_account_scoped_for_other_account_not_returned(account, account_b):
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import resolve_rubric

    g = _make_rubric(
        slug="g",
        version=1,
        scope=AssessmentRubric.Scope.GLOBAL,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    _make_rubric(
        slug="a",
        version=1,
        scope=AssessmentRubric.Scope.ACCOUNT,
        account=account,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    result = resolve_rubric(
        account=account_b, lab_type="chatlab", assessment_type="initial_feedback"
    )
    assert result.pk == g.pk


def test_lab_type_mismatch_raises():
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import RubricNotFoundError, resolve_rubric

    _make_rubric(
        slug="r",
        version=1,
        scope=AssessmentRubric.Scope.GLOBAL,
        status=AssessmentRubric.Status.PUBLISHED,
        lab_type="chatlab",
    )
    with pytest.raises(RubricNotFoundError):
        resolve_rubric(account=None, lab_type="trainerlab", assessment_type="initial_feedback")


def test_assessment_type_mismatch_raises():
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import RubricNotFoundError, resolve_rubric

    _make_rubric(
        slug="r",
        version=1,
        scope=AssessmentRubric.Scope.GLOBAL,
        status=AssessmentRubric.Status.PUBLISHED,
        assessment_type="initial_feedback",
    )
    with pytest.raises(RubricNotFoundError):
        resolve_rubric(
            account=None,
            lab_type="chatlab",
            assessment_type="continuation_feedback",
        )


def test_account_none_only_matches_global(account):
    from apps.assessments.models import AssessmentRubric
    from apps.assessments.services import RubricNotFoundError, resolve_rubric

    _make_rubric(
        slug="a",
        version=1,
        scope=AssessmentRubric.Scope.ACCOUNT,
        account=account,
        status=AssessmentRubric.Status.PUBLISHED,
    )
    # Only an account-scoped rubric exists; with account=None, fall back
    # to GLOBAL — none exists, so we raise.
    with pytest.raises(RubricNotFoundError):
        resolve_rubric(account=None, lab_type="chatlab", assessment_type="initial_feedback")
