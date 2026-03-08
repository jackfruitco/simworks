from __future__ import annotations

from ninja.errors import HttpError

from apps.accounts.models import LabMembership

LAB_SLUG = "trainerlab"
ACCESS_RANK = {
    LabMembership.AccessLevel.VIEWER: 10,
    LabMembership.AccessLevel.INSTRUCTOR: 20,
    LabMembership.AccessLevel.ADMIN: 30,
}


def get_membership(user, *, lab_slug: str = LAB_SLUG) -> LabMembership | None:
    return (
        LabMembership.objects.select_related("lab")
        .filter(user=user, lab__slug=lab_slug, lab__is_active=True, is_active=True)
        .first()
    )


def require_instructor_membership(user, *, lab_slug: str = LAB_SLUG) -> LabMembership:
    if user.is_superuser:
        # Superusers bypass explicit membership for operational access.
        return LabMembership(access_level=LabMembership.AccessLevel.ADMIN)

    membership = get_membership(user, lab_slug=lab_slug)
    if membership is None:
        raise HttpError(403, "TrainerLab membership required")

    if (
        ACCESS_RANK.get(membership.access_level, 0)
        < ACCESS_RANK[LabMembership.AccessLevel.INSTRUCTOR]
    ):
        raise HttpError(403, "Instructor access required")

    return membership
