from __future__ import annotations

from django.db import models, transaction
from django.utils import timezone

from apps.accounts.permissions import get_account_membership
from apps.accounts.services import get_personal_account_for_user
from apps.billing.catalog import (
    canonicalize_product_code,
    get_product,
    is_valid_product_code,
)
from apps.billing.models import Entitlement, SeatAllocation, SeatAssignment

ACTIVE_STATUSES = {Entitlement.Status.ACTIVE, Entitlement.Status.SCHEDULED}


def _is_current(entitlement: Entitlement, at=None) -> bool:
    at = at or timezone.now()
    if entitlement.status not in ACTIVE_STATUSES:
        return False
    if entitlement.starts_at and entitlement.starts_at > at:
        return False
    return not (entitlement.ends_at and entitlement.ends_at < at)


def _current_entitlements_for_account(account, *, user=None):
    queryset = Entitlement.objects.filter(account=account).select_related("subject_user")
    if user is None:
        return [ent for ent in queryset if _is_current(ent)]

    rows = []
    for entitlement in queryset:
        if not _is_current(entitlement):
            continue
        if entitlement.scope_type == Entitlement.ScopeType.ACCOUNT:
            rows.append(entitlement)
            continue
        if entitlement.subject_user_id == user.id:
            rows.append(entitlement)
    return rows


def _portable_personal_entitlements(user, *, account):
    if not getattr(user, "is_authenticated", False):
        return []
    personal_account = get_personal_account_for_user(user)
    if personal_account.id == account.id:
        return []
    rows = []
    for entitlement in _current_entitlements_for_account(personal_account, user=user):
        if (
            entitlement.scope_type == Entitlement.ScopeType.USER
            and entitlement.subject_user_id == user.id
            and entitlement.portable_across_accounts
        ):
            rows.append(entitlement)
    return rows


def _canonical_product_code(value: str | None) -> str:
    canonical_value = canonicalize_product_code(value)
    if is_valid_product_code(canonical_value):
        return canonical_value
    return ""


def _is_valid_base_product_entitlement(entitlement: Entitlement) -> bool:
    return bool(
        _canonical_product_code(entitlement.product_code)
        and not entitlement.feature_code
        and not entitlement.limit_code
    )


def _personal_account_auto_seat_applies(account, user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if not getattr(account, "is_personal", False):
        return False
    if account.owner_user_id != user.id:
        return False
    return get_account_membership(user, account) is not None


def _has_active_seat(account, user, product_code: str, *, at=None) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    canonical_product_code = _canonical_product_code(product_code)
    if not canonical_product_code:
        return False
    if not get_product(canonical_product_code).seat_gated:
        return True
    if _personal_account_auto_seat_applies(account, user):
        return True
    at = at or timezone.now()
    if (
        not SeatAllocation.objects.filter(
            account=account,
            product_code=canonical_product_code,
            effective_from__lte=at,
        )
        .filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=at))
        .exists()
    ):
        return True
    return SeatAssignment.objects.filter(
        account=account,
        user=user,
        product_code=canonical_product_code,
        assigned_at__lte=at,
        ended_at__isnull=True,
    ).exists()


def get_effective_entitlements(user, account):
    entitlements = list(_current_entitlements_for_account(account, user=user))
    entitlements.extend(_portable_personal_entitlements(user, account=account))
    unique = {}
    for entitlement in entitlements:
        canonical_product_code = _canonical_product_code(entitlement.product_code) or (
            entitlement.product_code or ""
        )
        key = (
            entitlement.account_id,
            entitlement.scope_type,
            entitlement.subject_user_id,
            canonical_product_code,
            entitlement.feature_code,
            entitlement.limit_code,
            entitlement.source_type,
            entitlement.source_ref,
        )
        if canonical_product_code and canonical_product_code != entitlement.product_code:
            entitlement.product_code = canonical_product_code
        unique[key] = entitlement
    return list(unique.values())


def has_product_access(user, account, product_code: str) -> bool:
    canonical_product_code = _canonical_product_code(product_code)
    if not canonical_product_code:
        return False
    for entitlement in get_effective_entitlements(user, account):
        if not _is_valid_base_product_entitlement(entitlement):
            continue
        if _canonical_product_code(entitlement.product_code) != canonical_product_code:
            continue
        if (
            entitlement.account_id == account.id
            and not entitlement.portable_across_accounts
            and not _has_active_seat(account, user, canonical_product_code)
        ):
            continue
        return True
    return False


def has_feature_access(user, account, product_code: str, feature_code: str) -> bool:
    del user, account, product_code, feature_code
    return False


def get_limit(user, account, product_code: str, limit_code: str):
    del user, account, product_code, limit_code
    return None


@transaction.atomic
def grant_demo_product_access(
    user, account, product_code: str, source_ref: str = ""
) -> Entitlement:
    canonical_product_code = _canonical_product_code(product_code)
    if not canonical_product_code:
        raise ValueError(f"Unknown product code: {product_code}")

    is_personal_owner = getattr(account, "is_personal", False) and account.owner_user_id == getattr(
        user, "id", None
    )
    if is_personal_owner:
        scope_type = Entitlement.ScopeType.USER
        subject_user_id = user.id
        portable_across_accounts = True
    else:
        scope_type = Entitlement.ScopeType.ACCOUNT
        subject_user_id = None
        portable_across_accounts = False

    return Entitlement.objects.update_or_create(
        account=account,
        source_type=Entitlement.SourceType.GRANT,
        source_ref=source_ref or f"demo:{canonical_product_code}:{account.pk}",
        scope_type=scope_type,
        subject_user_id=subject_user_id,
        product_code=canonical_product_code,
        feature_code="",
        limit_code="",
        defaults={
            "limit_value": None,
            "status": Entitlement.Status.ACTIVE,
            "portable_across_accounts": portable_across_accounts,
            "starts_at": timezone.now(),
            "ends_at": None,
            "metadata": {"granted_via": "grant_demo_product_access"},
        },
    )[0]


def get_access_snapshot(user, account):
    membership = get_account_membership(user, account)
    products: dict[str, dict] = {}
    seen: set[str] = set()
    for entitlement in get_effective_entitlements(user, account):
        if not _is_valid_base_product_entitlement(entitlement):
            continue
        canonical_product_code = _canonical_product_code(entitlement.product_code)
        if not canonical_product_code or canonical_product_code in seen:
            continue
        seen.add(canonical_product_code)
        if has_product_access(user, account, canonical_product_code):
            products[canonical_product_code] = {"enabled": True, "features": {}, "limits": {}}
    return {
        "account_uuid": str(account.uuid),
        "account_name": account.name,
        "account_type": account.account_type,
        "membership_role": membership.role if membership else "",
        "products": products,
    }
