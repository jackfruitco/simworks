# simcore_ai_django/execution/base_backend.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Mapping, Optional

class BaseExecutionBackend(ABC):
    @abstractmethod
    def execute(
        self, *, service_cls, kwargs: Mapping[str, Any]
    ) -> Any:
        ...

    @abstractmethod
    def enqueue(
        self, *,
        service_cls,
        kwargs: Mapping[str, Any],
        delay_s: Optional[float] = None,
        queue: Optional[str] = None,
    ) -> str:
        ...