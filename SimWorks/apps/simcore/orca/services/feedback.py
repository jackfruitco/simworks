# simcore/orca/services/feedback.py
"""
Feedback AI Services for Simulation using Pydantic AI.

Services compose instructions via MRO inheritance from BaseInstruction classes.
Pydantic AI handles execution and validation.

WORKFLOW DIAGRAM
================

    GenerateInitialFeedback / GenerateFeedbackContinuationReply
      -> Instructions composed from class hierarchy via MRO
      -> Pydantic AI Agent.run() with result_type
      -> Pydantic AI validates response automatically
      -> store RunResult to ServiceCall (JSON)
      -> [async] drain worker calls persistence handler
      -> persistence handler: ensure_idempotent() -> model_validate() -> ORM creates
      -> return RunResult (contains validated output as Pydantic model)

COERCION BOUNDARY
=================
Provider response -> Pydantic AI validation -> strict Pydantic model (result.output)

PERSISTENCE CONTRACT
====================
- Persistence handlers receive: RunResult with output (validated Pydantic model)
- Creates: SimulationFeedback rows
- Idempotency: PersistedChunk with (call_id, schema_identity) unique constraint
"""

import logging
from typing import ClassVar

from apps.common.orca.instructions import (
    FeedbackEducatorInstruction,
    MedicalAccuracyInstruction,
)
from apps.simcore.orca.instructions import (
    FeedbackContinuationInstruction,
    FeedbackInitialInstruction,
)
from orchestrai_django.components.services import DjangoBaseService
from orchestrai_django.decorators import service
from ..mixins import FeedbackMixin  # Identity mixin for component discovery

logger = logging.getLogger(__name__)


@service
class GenerateInitialFeedback(
    FeedbackInitialInstruction,              # order=0  - initial feedback evaluation criteria
    FeedbackEducatorInstruction,             # order=5  - medical educator persona
    MedicalAccuracyInstruction,              # order=15 - clinical accuracy enforcement
    FeedbackMixin,  # Identity mixin
    DjangoBaseService,
):
    """Generate the initial patient feedback.

    Instructions are composed from the class hierarchy via MRO.
    """

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True

    from apps.simcore.orca.schemas import GenerateInitialSimulationFeedback as _Schema
    response_schema = _Schema


@service
class GenerateFeedbackContinuationReply(
    FeedbackContinuationInstruction,         # order=0  - continuation instructions
    FeedbackEducatorInstruction,             # order=5  - medical educator persona
    FeedbackMixin,  # Identity mixin
    DjangoBaseService,
):
    """Generate continuation feedback.

    Instructions are composed from the class hierarchy via MRO.
    """

    required_context_keys: ClassVar[tuple[str, ...]] = ("simulation_id",)
    use_native_output = True
