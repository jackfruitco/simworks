"""Shared utilities for API v1 endpoints."""

from ninja.errors import HttpError


def get_simulation_for_user(simulation_id: int, user):
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

    try:
        return Simulation.objects.get(pk=simulation_id, user=user)
    except Simulation.DoesNotExist as err:
        raise HttpError(404, "Simulation not found") from err
