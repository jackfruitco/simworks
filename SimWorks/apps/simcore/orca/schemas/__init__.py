# simcore/orca/schemas/__init__.py
"""
Simulation schemas for Pydantic AI.

These are plain Pydantic models used as result_type for Pydantic AI agents.
Pydantic AI handles validation natively - no @schema decorator needed.
"""

from .feedback import (
    FeedbackContinuationBlock,
    GenerateFeedbackContinuationResponse,
    GenerateInitialSimulationFeedback,
)
from .metadata_items import (
    LabResultItem,
    MetadataItem,
    PatientDemographicsItem,
    PatientHistoryItem,
    RadResultItem,
    SimulationMetadataItem,
)
from .output_items import InitialFeedbackBlock, LLMConditionsCheckItem

__all__ = [
    "FeedbackContinuationBlock",
    "GenerateFeedbackContinuationResponse",
    "GenerateInitialSimulationFeedback",
    "InitialFeedbackBlock",
    "LLMConditionsCheckItem",
    "LabResultItem",
    "MetadataItem",
    "PatientDemographicsItem",
    "PatientHistoryItem",
    "RadResultItem",
    "SimulationMetadataItem",
]
