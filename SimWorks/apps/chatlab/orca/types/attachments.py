from typing import Any, Literal

from pydantic import Field

from orchestrai_django.types import StrictBaseModel


class AttachmentItem(StrictBaseModel):
    kind: Literal["image"]
    b64: str | None = None
    file: Any | None = None
    url: str | None = None

    format: str | None = None  # "png", "jpeg"
    size: str | None = None  # "1024x1024"
    background: str | None = None

    provider_meta: dict[str, Any] = Field(default_factory=dict)

    # linkage after persistence
    db_pk: int | None = None
    db_model: str | None = None
    slug: str | None = None
