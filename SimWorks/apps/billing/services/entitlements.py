from __future__ import annotations

from collections import defaultdict

from django.db import models
from django.utils import timezone

from apps.accounts.permissions import get_account_membership
from apps.accounts.services import get_personal_account_for_user
from apps.billing.models import Entitlement, SeatAllocation, SeatAssignment


ACTIVE_STATUSES = {Entitlement.Status.ACTIVE, Entitlement.Status.SCHEDULED}


def _is_current(entitlement: Entitlement, at=None) -> bool:
    at = at or timezone.now()
    if entitlement.status not in ACTIVE_STATUSES:
        return False
    if entitlement.starts_at and entitlement.starts_at > at:
        return False
    if entitlement.ends_at and entitlement.ends_at < at:
        return False
    return True


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


def _has_active_seat(account, user, product_code: str, *, at=None) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    at = at or timezone.now()
    if not SeatAllocation.objects.filter(
        account=account,
        product_code=product_code,
        effective_from__lte=at,
    ).filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=at)).exists():
        return True
    return SeatAssignment.objects.filter(
        account=account,
        user=user,
        product_code=product_code,
        assigned_at__lte=at,
        ended_at__isnull=True,
    ).exists()


def get_effective_entitlements(user, account):
    entitlements = list(_current_entitlements_for_account(account, user=user))
    entitlements.extend(_portable_personal_entitlements(user, account=account))
    unique = {}
    for entitlement in entitlements:
        key = (
            entitlement.account_id,
            entitlement.scope_type,
            entitlement.subject_user_id,
            entitlement.product_code,
            entitlement.feature_code,
            entitlement.limit_code,
            entitlement.source_type,
            entitlement.source_ref,
        )
        unique[key] = entitlement
    return list(unique.values())


def has_product_access(user, account, product_code: str) -> bool:
    for entitlement in get_effective_entitlements(user, account):
        if entitlement.product_code != product_code:
            continue
        if entitlement.feature_code or entitlement.limit_code:
            continue
        if entitlement.account_id == account.id and not entitlement.portable_across_accounts:
            if not _has_active_seat(account, user, product_code):
                continue
        return True
    return False


def has_feature_access(user, account, product_code: str, feature_code: str) -> bool:
    for entitlement in get_effective_entitlements(user, account):
        if entitlement.product_code == product_code and entitlement.feature_code == feature_code:
            if entitlement.account_id == account.id and not entitlement.portable_across_accounts:
                if not _has_active_seat(account, user, product_code):
                    continue
            return True
    return False


def get_limit(user, account, product_code: str, limit_code: str):
    values = []
    for entitlement in get_effective_entitlements(user, account):
        if entitlement.product_code == product_code and entitlement.limit_code == limit_code:
            values.append(entitlement.limit_value or 0)
    return max(values) if values else None


def get_access_snapshot(user, account):
    membership = get_account_membership(user, account)
    products: dict[str, dict] = defaultdict(lambda: {"features": [], "limits": {}})
    for entitlement in get_effective_entitlements(user, account):
        if entitlement.feature_code:
            products[entitlement.product_code]["features"].append(entitlement.feature_code)
        elif entitlement.limit_code:
            products[entitlement.product_code]["limits"][entitlement.limit_code] = (
                entitlement.limit_value
            )
        else:
            products[entitlement.product_code]["enabled"] = True
    return {
        "account_uuid": str(account.uuid),
        "account_name": account.name,
        "account_type": account.account_type,
        "membership_role": membership.role if membership else "",
        "products": dict(products),
    }
