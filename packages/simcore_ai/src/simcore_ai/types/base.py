# simcore_ai/types/base.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

class StrictBaseModel(BaseModel):
    """Default strict model used across SimWorks."""
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StrictOutputSchema(StrictBaseModel):
    """Marker/base for LLM output schemas."""
    pass


Boolish = Literal["true", "false", "partial"]
