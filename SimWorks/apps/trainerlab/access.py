from __future__ import annotations

from ninja.errors import HttpError

from apps.accounts.context import resolve_account_for_user, resolve_request_account
from apps.accounts.models import LabMembership
from apps.billing.catalog import product_codes_for_lab
from apps.billing.services.entitlements import has_product_access

LAB_SLUG = "trainerlab"


def has_lab_access(user, account, *, lab_slug: str = LAB_SLUG) -> bool:
    """Return True when *user* has effective product access for *lab_slug* in *account*."""
    if account is None:
        return False
    return any(
        has_product_access(user, account, pc)
        for pc in product_codes_for_lab(lab_slug)
    )


def _legacy_membership(user, *, lab_slug: str = LAB_SLUG) -> LabMembership | None:
    return (
        LabMembership.objects.select_related("lab")
        .filter(user=user, lab__slug=lab_slug, lab__is_active=True, is_active=True)
        .first()
    )


def check_lab_access(user, *, lab_slug: str = LAB_SLUG, request=None) -> bool:
    """Check entitlement-based lab access, falling back to legacy membership."""
    account = (
        resolve_request_account(request, user=user) if request else resolve_account_for_user(user)
    )
    if has_lab_access(user, account, lab_slug=lab_slug):
        return True
    return _legacy_membership(user, lab_slug=lab_slug) is not None


def has_lab_access_for_request(user, *, lab_slug: str = LAB_SLUG, request=None) -> bool:
    """Public helper used by views to gate access."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return check_lab_access(user, lab_slug=lab_slug, request=request)


def require_lab_access(user, *, lab_slug: str = LAB_SLUG, request=None) -> bool:
    """Raise 403 when the user lacks lab access.  Returns True on success."""
    if user.is_superuser:
        return True
    if not check_lab_access(user, lab_slug=lab_slug, request=request):
        raise HttpError(403, "TrainerLab access required")
    return True
