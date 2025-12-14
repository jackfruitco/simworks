

from typing import Literal, Optional, Any, Dict

from pydantic import Field

from orchestrai_django.types import StrictBaseModel


class AttachmentItem(StrictBaseModel):
    kind: Literal["image"]
    b64: Optional[str] = None
    file: Optional[Any] = None
    url: Optional[str] = None

    format: Optional[str] = None  # "png", "jpeg"
    size: Optional[str] = None  # "1024x1024"
    background: Optional[str] = None

    provider_meta: Dict[str, Any] = Field(default_factory=dict)

    # linkage after persistence
    db_pk: Optional[int] = None
    db_model: Optional[str] = None
    slug: Optional[str] = None
