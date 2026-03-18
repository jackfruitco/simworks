# trainerlab/orca/schemas/vitals.py

from pydantic import Field

from orchestrai.types import StrictBaseModel

from .runtime import RuntimeVitalUpdate


class VitalsProgressionOutput(StrictBaseModel):
    """
    Output schema for the GenerateVitalsProgression service.

    Contains only vital sign updates and a brief clinical rationale.
    Conditions and interventions are read-only context; do not mutate them here.

    **Identity**: schemas.trainerlab.vitals.VitalsProgressionOutput
    """

    vitals: list[RuntimeVitalUpdate] = Field(
        ...,
        min_length=1,
        description="Updated vital sign ranges for all active vital types.",
    )
    rationale: str = Field(
        default="",
        description="Brief clinical explanation of why these vital values changed.",
    )
