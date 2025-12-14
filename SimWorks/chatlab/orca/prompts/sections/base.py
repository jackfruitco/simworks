from dataclasses import dataclass
from typing import Any

from orchestrai_django.components.promptkit import PromptSection
from orchestrai_django.decorators import prompt_section

from simulation.orca.mixins import StandardizedPatientMixin
from ...mixins import ChatlabMixin


@prompt_section
@dataclass
class ChatlabBaseSection(ChatlabMixin, PromptSection):
    """Base class for prompt sections."""

    weight: int = 1
    instruction: str = (
        "### General"
        "\n"
        "You are a standardized patient role player for medical training."
        "\n"
        "Select a diagnosis and develop a corresponding clinical scenario "
        "script using simple, everyday language that reflects the knowledge "
        "level of an average person."
        "\n"
    )
    message: str = ""
