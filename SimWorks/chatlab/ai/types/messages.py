

from typing import Optional, List, Dict, Any

from pydantic import Field

from chatlab.ai.types.attachments import AttachmentItem
from simcore_ai_django.types import StrictBaseModel


class MessageItem(StrictBaseModel):
    role: str
    content: str

    db_pk: Optional[int] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    attachments: List[AttachmentItem] = Field(default_factory=list)
