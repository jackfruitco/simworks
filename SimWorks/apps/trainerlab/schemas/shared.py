from __future__ import annotations

from pydantic import Field

from orchestrai.types import StrictBaseModel


class ScenarioBrief(StrictBaseModel):
    read_aloud_brief: str = Field(
        ...,
        min_length=1,
        description=(
            "A concise instructor read-aloud brief delivered to the trainee before the simulation "
            "begins."
        ),
    )
    environment: str = Field(default="", description="Simulation environment and overall setting.")
    location_overview: str = Field(
        default="",
        description="Approximate location and terrain or facility context.",
    )
    threat_context: str = Field(
        default="",
        description="Enemy, threat, or scene-safety context when applicable.",
    )
    evacuation_options: list[str] = Field(
        default_factory=list,
        description="Available evacuation or transport options, if known.",
    )
    evacuation_time: str = Field(
        default="",
        description="Expected evacuation time or transport delay when applicable.",
    )
    special_considerations: list[str] = Field(
        default_factory=list,
        description="Other constraints or scenario considerations the instructor should know.",
    )


class RuntimePatientStatus(StrictBaseModel):
    avpu: str | None = None
    respiratory_distress: bool = False
    hemodynamic_instability: bool = False
    impending_pneumothorax: bool = False
    tension_pneumothorax: bool = False
    narrative: str = ""
    teaching_flags: list[str] = Field(default_factory=list)


class RuntimeInstructorIntent(StrictBaseModel):
    summary: str = ""
    rationale: str = ""
    trigger: str = ""
    eta_seconds: int | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    upcoming_changes: list[str] = Field(default_factory=list)
    monitoring_focus: list[str] = Field(default_factory=list)
