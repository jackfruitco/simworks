# orchestrai/types/build.py
"""
Build-side message and metadata types for ergonomic construction.

These types are used for:
- Constructing messages in application code
- Building request payloads
- Adapting provider responses

Key characteristics:
- May have defaults on fields for ergonomic construction
- Can be converted to Result* types for schema validation/persistence

DO NOT use these in schema definitions - use Result* types instead.
"""

from pydantic import Field, BaseModel

from .content import ContentRole
from .build_content import BuildContent
from .meta import Metafield

__all__ = (
    "BuildMessageItem",
    "BuildMetafield",
)


# ---- Build-side metadata ----

class BuildMetafield(BaseModel):
    """
    Metadata field for construction - ergonomic, allows flexibility.

    For schema definitions, use ResultMetafield instead.
    """
    key: str = Field(..., min_length=1, description="Metadata key identifier")
    value: str | int | float | bool | None = Field(
        ...,
        description="Metadata value - JSON primitive types only"
    )


# ---- Build-side message item ----

class BuildMessageItem(BaseModel):
    """
    Message item for construction - ergonomic defaults provided.

    Used for:
    - Building messages in application code
    - Constructing request payloads
    - Adapting provider responses

    Defaults provided for convenience. For schema definitions, use ResultMessageItem.
    """
    role: ContentRole
    content: list[BuildContent]
    item_meta: list[BuildMetafield] = Field(
        default_factory=list,  # Default empty list for convenience
        description="Metadata entries as key-value pairs"
    )
