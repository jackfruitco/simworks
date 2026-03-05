# simcore/ai/types/base.py


import logging
from typing import Any

from pydantic import Field

from orchestrai_django.types import StrictBaseModel

logger = logging.getLogger(__name__)


# ---------- Metadata (DTO) ---------------------------------------------------------


# ---------- Tools (DTO) ------------------------------------------------------------
class ToolItem(StrictBaseModel):
    kind: str  # e.g., "image_generation"
    function: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
