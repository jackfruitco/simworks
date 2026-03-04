from typing import Any

from pydantic import Field

from apps.chatlab.orca.types.attachments import AttachmentItem
from orchestrai_django.types import StrictBaseModel


class MessageItem(StrictBaseModel):
    role: str
    content: str

    db_pk: int | None = None
    tool_calls: list[dict[str, Any]] | None = None
    attachments: list[AttachmentItem] = Field(default_factory=list)
