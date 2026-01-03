# orchestrai/components/schemas/base.py

from typing import ClassVar

from orchestrai.identity import IdentityMixin
from orchestrai.identity.domains import SCHEMAS_DOMAIN
from orchestrai.types import StrictBaseModel


class BaseOutputItem(StrictBaseModel):
    """Default Pydantic model for LLM output schema items."""
    pass


class BaseOutputSchema(StrictBaseModel, IdentityMixin):
    """Default Pydantic model for LLM output schemas.

    Async-first registry access with a sync convenience wrapper.
    """
    DOMAIN: ClassVar[str] = SCHEMAS_DOMAIN
    domain: ClassVar[str | None] = SCHEMAS_DOMAIN
