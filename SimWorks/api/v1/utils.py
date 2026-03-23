"""Shared utilities for API v1 endpoints."""

from django.db.models import Q
from ninja.errors import HttpError

from apps.accounts.context import resolve_request_account
from apps.accounts.permissions import can_view_account_runs, can_view_simulation


def get_account_for_request(request, user):
    account = resolve_request_account(request, user=user)
    if account is None:
        raise HttpError(403, "Account access denied")
    return account


def get_simulation_queryset_for_request(request, user):
    account = get_account_for_request(request, user)
    legacy_fallback = Q(pk__in=[])
    if getattr(account, "is_personal", False) and account.owner_user_id == getattr(
        user, "id", None
    ):
        legacy_fallback = Q(account__isnull=True, user=user)
    from apps.simcore.models import Simulation

    queryset = Simulation.objects.filter(Q(account=account) | legacy_fallback).select_related(
        "account"
    )
    if can_view_account_runs(user, account):
        return queryset
    return queryset.filter(user=user)


def get_simulation_for_user(simulation_id: int, user, request=None):
    """Get a simulation, ensuring the user has access.

    Args:
        simulation_id: The simulation ID to retrieve
        user: The user making the request

    Returns:
        Simulation instance if found and owned by user

    Raises:
        HttpError: 404 if simulation not found or not owned by user
    """
    from apps.simcore.models import Simulation

    if request is not None:
        queryset = get_simulation_queryset_for_request(request, user)
        try:
            simulation = queryset.get(pk=simulation_id)
        except Simulation.DoesNotExist as err:
            raise HttpError(404, "Simulation not found") from err
        if not can_view_simulation(user, simulation):
            raise HttpError(404, "Simulation not found")
        return simulation

    try:
        simulation = Simulation.objects.select_related("account").get(pk=simulation_id, user=user)
    except Simulation.DoesNotExist as err:
        raise HttpError(404, "Simulation not found") from err
    if simulation.account_id and not can_view_simulation(user, simulation):
        raise HttpError(404, "Simulation not found")
    return simulation
