# orchestrai/components/schemas/__init__.py
"""
OrchestrAI Schemas Module (DEPRECATED).

.. deprecated:: 0.5.0
    The @schema decorator and BaseOutputSchema are deprecated.
    Use plain Pydantic BaseModel classes as response_schema instead.
    Pydantic AI validates structured output natively.

Migration Guide:
    Before:
        from orchestrai_django.decorators import schema
        from orchestrai.components.schemas import BaseOutputSchema

        @schema
        class MyOutputSchema(BaseOutputSchema):
            messages: list[str]

    After:
        from pydantic import BaseModel

        class MyOutputSchema(BaseModel):
            messages: list[str]

        class MyService(PydanticAIService):
            response_schema = MyOutputSchema
"""
import warnings

warnings.warn(
    "orchestrai.components.schemas is deprecated and will be removed in OrchestrAI 1.0. "
    "Use plain Pydantic BaseModel classes instead.",
    DeprecationWarning,
    stacklevel=2,
)

from .base import BaseOutputSchema, BaseOutputItem
from .helpers import sort_adapters
from .adapters import BaseSchemaAdapter, BaseOutputAdapter

__all__ = (
    "BaseOutputSchema",
    "BaseOutputItem",
    "BaseSchemaAdapter",
    "BaseOutputAdapter",
    "sort_adapters",
)
