"""Rubric resolution: pick the best published rubric for a request.

Resolution rules (per implementation plan):

1. Highest-version PUBLISHED account-scoped rubric matching
   ``(account, lab_type, assessment_type)``.
2. Otherwise the highest-version PUBLISHED global rubric matching
   ``(lab_type, assessment_type)``.

The function raises :class:`RubricNotFoundError` if neither exists.
"""

from __future__ import annotations

from django.db.models import Case, IntegerField, Q, When

from apps.assessments.models import AssessmentRubric


class RubricNotFoundError(LookupError):
    """Raised when no published rubric matches the resolution request."""


def resolve_rubric(*, account, lab_type: str, assessment_type: str) -> AssessmentRubric:
    """Resolve the rubric to use for the given request.

    Args:
        account: The accounts.Account instance (or ``None`` for global-only).
        lab_type: e.g. ``"chatlab"``.
        assessment_type: e.g. ``"initial_feedback"``.

    Returns:
        The matching :class:`AssessmentRubric`.

    Raises:
        RubricNotFoundError: When no candidate exists.
    """
    queryset = (
        AssessmentRubric.objects.filter(
            status=AssessmentRubric.Status.PUBLISHED,
            lab_type=lab_type,
            assessment_type=assessment_type,
        )
        .filter(
            Q(scope=AssessmentRubric.Scope.ACCOUNT, account=account)
            | Q(scope=AssessmentRubric.Scope.GLOBAL, account__isnull=True)
        )
        .annotate(
            scope_priority=Case(
                When(scope=AssessmentRubric.Scope.ACCOUNT, then=0),
                default=1,
                output_field=IntegerField(),
            )
        )
        .order_by("scope_priority", "-version", "-published_at")
    )

    rubric = queryset.first()
    if rubric is None:
        raise RubricNotFoundError(
            f"No published rubric for lab_type={lab_type!r} "
            f"assessment_type={assessment_type!r} account={account!r}."
        )
    return rubric
