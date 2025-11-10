# simcore_ai/components/schemas/base.py
from __future__ import annotations

from asgiref.sync import async_to_sync

from simcore_ai.identity import IdentityMixin
from simcore_ai.registry import BaseRegistry
from simcore_ai.types import StrictBaseModel


class BaseOutputItem(StrictBaseModel):
    """Default Pydantic model for LLM output schema items."""
    pass


class BaseOutputSchema(StrictBaseModel, IdentityMixin):
    """Default Pydantic model for LLM output schemas.

    Async-first registry access with a sync convenience wrapper.
    """

    @classmethod
    async def aget_registry(cls) -> BaseRegistry:
        """
        Async registry accessor for output schemas.

        Returns the shared schema registry for this schema type.
        """
        from simcore_ai.registry.singletons import schemas
        return schemas

    @classmethod
    def get_registry(cls) -> BaseRegistry:
        """
        Sync wrapper for `aget_registry`.

        Use in sync-only contexts (e.g. __init_subclass__, migrations, tests).
        """
        return async_to_sync(cls.aget_registry)()