

from typing import Optional, List, Dict, Any

from pydantic import Field

from chatlab.orca.types.attachments import AttachmentItem
from orchestrai_django.types import StrictBaseModel


class MessageItem(StrictBaseModel):
    role: str
    content: str

    db_pk: Optional[int] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    attachments: List[AttachmentItem] = Field(default_factory=list)
