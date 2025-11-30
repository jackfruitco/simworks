# simcore-ai/components/schemas/adapter.py
"""
Base adapter classes for adapting schemas or outputs.

This module provides abstract base classes for implementing schema and
output adapters that standardize the structure or output of data.

"""
from typing import overload, Any

import ABC

from ...types.content import BaseToolResultContent, BaseToolCallContent


class BaseAdapter(ABC):
    @overload
    def adapt(self, target_: Dict[str, Any]) -> dict[str, Any]: ...
    @overload
    def adapt(self, target_: Any) -> tuple[BaseToolCallContent, BaseToolResultContent] | None: ...
    def adapt(self, target_) -> Any:
        """Adapt """
        raise NotImplementedError

    provider_slug: str | None = None
    adapter_kind: literal["schema", "ouput"]
    order: int = 0  # lower values are applied first


class BaseSchemaAdapter(BaseAdapter):
    adapter_kind = "schema"


class BaseOutputAdapter(BaseAdapter):
    adapter_kind = "output"
