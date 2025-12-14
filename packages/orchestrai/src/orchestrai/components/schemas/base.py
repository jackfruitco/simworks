# orchestrai/components/schemas/base.py

from orchestrai.identity import IdentityMixin
from orchestrai.types import StrictBaseModel


class BaseOutputItem(StrictBaseModel):
    """Default Pydantic model for LLM output schema items."""
    pass


class BaseOutputSchema(StrictBaseModel, IdentityMixin):
    """Default Pydantic model for LLM output schemas.

    Async-first registry access with a sync convenience wrapper.
    """
    pass
