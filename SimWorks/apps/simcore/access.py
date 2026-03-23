from __future__ import annotations

from django.db.models import Q

from apps.accounts.context import resolve_request_account, resolve_scope_account
from apps.accounts.permissions import can_view_account_runs, can_view_simulation


def get_simulation_queryset_for_account(user, account):
    from apps.simcore.models import Simulation

    legacy_fallback = Q(pk__in=[])
    if getattr(account, "is_personal", False) and account.owner_user_id == getattr(user, "id", None):
        legacy_fallback = Q(account__isnull=True, user=user)
    queryset = Simulation.objects.filter(Q(account=account) | legacy_fallback).select_related(
        "account", "user"
    )
    if can_view_account_runs(user, account):
        return queryset
    return queryset.filter(user=user)


def get_simulation_queryset_for_request(request, user):
    from apps.simcore.models import Simulation

    account = resolve_request_account(request, user=user)
    if account is None:
        return Simulation.objects.none()
    return get_simulation_queryset_for_account(user, account)


def get_simulation_queryset_for_scope(scope, user):
    from apps.simcore.models import Simulation

    account = resolve_scope_account(scope, user)
    if account is None:
        return Simulation.objects.none()
    return get_simulation_queryset_for_account(user, account)


def can_access_simulation_in_request(user, simulation, request) -> bool:
    if not can_view_simulation(user, simulation):
        return False
    account = resolve_request_account(request, user=user)
    if account is None:
        return False
    if simulation.account_id is None:
        return bool(getattr(account, "is_personal", False) and account.owner_user_id == user.id)
    return simulation.account_id == account.id


def can_access_simulation_in_scope(user, simulation, scope) -> bool:
    if not can_view_simulation(user, simulation):
        return False
    account = resolve_scope_account(scope, user)
    if account is None:
        return False
    if simulation.account_id is None:
        return bool(getattr(account, "is_personal", False) and account.owner_user_id == user.id)
    return simulation.account_id == account.id
