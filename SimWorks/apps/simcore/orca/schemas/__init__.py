# simulation/orca/schemas/__init__.py
"""
Simulation schemas for Pydantic AI.

These are plain Pydantic models used as result_type for Pydantic AI agents.
Pydantic AI handles validation natively - no @schema decorator needed.
"""

from .feedback import GenerateInitialSimulationFeedback
from .output_items import LLMConditionsCheckItem, InitialFeedbackBlock
from .metadata_items import (
    MetadataItem,
    LabResultItem,
    RadResultItem,
    PatientHistoryItem,
    PatientDemographicsItem,
    SimulationMetadataItem,
)

__all__ = [
    "GenerateInitialSimulationFeedback",
    "LLMConditionsCheckItem",
    "InitialFeedbackBlock",
    "MetadataItem",
    "LabResultItem",
    "RadResultItem",
    "PatientHistoryItem",
    "PatientDemographicsItem",
    "SimulationMetadataItem",
]
