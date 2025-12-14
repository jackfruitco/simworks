# simcore/ai/types/base.py


import logging
from importlib import import_module
from typing import Any, Dict, Optional, List

from pydantic import Field

from chatlab.ai.types.messages import MessageItem
from chatlab.ai.types.metadata import MetafieldItem
from orchestrai_django.types import StrictBaseModel

logger = logging.getLogger(__name__)



# ---------- Metadata (DTO) ---------------------------------------------------------


# ---------- Tools (DTO) ------------------------------------------------------------
class ToolItem(StrictBaseModel):
    kind: str  # e.g., "image_generation"
    function: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)
