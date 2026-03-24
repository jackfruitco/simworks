from __future__ import annotations

from ninja.errors import HttpError

from apps.accounts.context import resolve_account_for_user, resolve_request_account
from apps.accounts.models import LabMembership
from apps.accounts.permissions import get_account_membership
from apps.billing.catalog import product_codes_for_lab
from apps.billing.services.entitlements import has_product_access

LAB_SLUG = "trainerlab"
ACCESS_RANK = {
    LabMembership.AccessLevel.VIEWER: 10,
    LabMembership.AccessLevel.INSTRUCTOR: 20,
    LabMembership.AccessLevel.ADMIN: 30,
}


def _legacy_membership(user, *, lab_slug: str = LAB_SLUG) -> LabMembership | None:
    return (
        LabMembership.objects.select_related("lab")
        .filter(user=user, lab__slug=lab_slug, lab__is_active=True, is_active=True)
        .first()
    )


def _derived_membership(user, account, *, lab_slug: str = LAB_SLUG) -> LabMembership | None:
    if account is None:
        return None
    if not any(
        has_product_access(user, account, product_code)
        for product_code in product_codes_for_lab(lab_slug)
    ):
        return None
    membership = get_account_membership(user, account)
    if (membership is None and account.owner_user_id == getattr(user, "id", None)) or (
        membership and membership.role == membership.Role.ORG_ADMIN
    ):
        access_level = LabMembership.AccessLevel.ADMIN
    elif membership and membership.role == membership.Role.INSTRUCTOR:
        access_level = LabMembership.AccessLevel.INSTRUCTOR
    elif membership and membership.role == membership.Role.GENERAL_USER:
        access_level = LabMembership.AccessLevel.VIEWER
    else:
        return None
    return LabMembership(access_level=access_level)


def get_membership(user, *, lab_slug: str = LAB_SLUG, request=None) -> LabMembership | None:
    account = (
        resolve_request_account(request, user=user) if request else resolve_account_for_user(user)
    )
    membership = _derived_membership(user, account, lab_slug=lab_slug)
    if membership is not None:
        return membership
    return _legacy_membership(user, lab_slug=lab_slug)


def has_instructor_access(user, *, lab_slug: str = LAB_SLUG, request=None) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False

    if user.is_superuser:
        return True

    membership = get_membership(user, lab_slug=lab_slug, request=request)
    if membership is None:
        return False

    return (
        ACCESS_RANK.get(membership.access_level, 0)
        >= ACCESS_RANK[LabMembership.AccessLevel.INSTRUCTOR]
    )


def require_instructor_membership(user, *, lab_slug: str = LAB_SLUG, request=None) -> LabMembership:
    if user.is_superuser:
        # Superusers bypass explicit membership for operational access.
        return LabMembership(access_level=LabMembership.AccessLevel.ADMIN)

    membership = get_membership(user, lab_slug=lab_slug, request=request)
    if membership is None:
        raise HttpError(403, "TrainerLab membership required")

    if (
        ACCESS_RANK.get(membership.access_level, 0)
        < ACCESS_RANK[LabMembership.AccessLevel.INSTRUCTOR]
    ):
        raise HttpError(403, "Instructor access required")

    return membership
