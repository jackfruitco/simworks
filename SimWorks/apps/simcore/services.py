from __future__ import annotations

from .models import Simulation


def is_simulation_billable(simulation: "Simulation") -> bool:
    """Returns False for failed simulations (non-billable for quota purposes).

    Raw session-level UsageRecord rows are always preserved regardless.
    Only customer-facing user/account usage aggregation is affected.
    """
    return simulation.status != Simulation.SimulationStatus.FAILED
