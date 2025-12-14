# orchestrai/components/schemas/adapter.py
"""
Base adapter classes for adapting schemas or outputs.

This module provides abstract base classes for implementing schema and
output adapters that standardize the structure or output of data.

"""
from typing import overload, Any, Literal

from abc import ABC

from ...types.content import BaseToolResultContent, BaseToolCallContent


class BaseAdapter(ABC):
    @overload
    def adapt(self, target_: dict[str, Any]) -> dict[str, Any]: ...
    @overload
    def adapt(self, target_: Any) -> tuple[BaseToolCallContent, BaseToolResultContent] | None: ...
    def adapt(self, target_) -> Any:
        """Adapt """
        raise NotImplementedError

    provider_slug: str | None = None
    adapter_kind: Literal["schema", "output"]
    order: int | None = None # lower values are applied first

    def __init__(
            self,
            order: int | None = None
    ):
        if order is not None:
            self.order = order
        else:
            self.order = 0


class BaseSchemaAdapter(BaseAdapter):
    adapter_kind = "schema"


class BaseOutputAdapter(BaseAdapter):
    adapter_kind = "output"
