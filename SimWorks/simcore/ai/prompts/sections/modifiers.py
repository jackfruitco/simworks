# simcore/ai/prompts/sections/modifiers.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ...promptkit import PromptSection, register_section

logger = logging.getLogger(__name__)


@dataclass
class BaseSection(PromptSection):
    category = "core"


@register_section
@dataclass
class PatientNameSection(BaseSection):
    name: str = "patient_name"

    async def render_instruction(self, **ctx) -> Optional[str]:

        full_name = ctx.get("sim_patient_full_name")

        simulation = ctx.get("simulation")
        if simulation and not full_name:
            from simcore.models import Simulation
            try:
                sim = await Simulation.aresolve(simulation)
                full_name = sim.sim_patient_full_name
            except Simulation.DoesNotExist:
                logger.warning(
                    f"PromptSection {self.label}:: Simulation {simulation} not found - skipping section."
                )
                return None

        if not full_name:
            logger.warning(
                f"PromptSection {self.label}:: Missing patient name (no simulation or sim_patient_full_name) - skipping."
            )
            return None

        return (
            f"You are roleplaying as {full_name}. "
            f"Use this name, and only this name, to identify yourself. "
            f"Do not break character."
        )