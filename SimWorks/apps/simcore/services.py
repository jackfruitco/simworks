from __future__ import annotations

from .models import Simulation


def is_simulation_billable(simulation: Simulation, *, lab_type: str = "") -> bool:
    """Returns False only for failed TrainerLab simulations (non-billable for quota).

    The billing exclusion is intentionally scoped to TrainerLab.  Failed
    simulations from other labs remain billable unless that rule is explicitly
    extended here.

    Raw session-level UsageRecord rows are always preserved regardless of this
    return value — only customer-facing user/account quota aggregation is affected.

    Args:
        simulation: The Simulation instance to check.
        lab_type:   The lab type string (e.g. "trainerlab", "chatlab").
                    Callers that have already resolved the lab type should pass it
                    to avoid redundant DB lookups.  Defaults to "" which conservatively
                    treats the simulation as billable unless it is clearly TrainerLab.
    """
    if simulation.status != Simulation.SimulationStatus.FAILED:
        return True
    return lab_type != "trainerlab"
