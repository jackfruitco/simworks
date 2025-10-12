from __future__ import annotations

from typing import Iterable, Optional, Type
from .types import PromptSection


class PromptRegistry:
    """
    Global store mapping label -> PromptSection subclass.
    We store CLASSES (not instances) so they can carry behavior.
    """
    _store: dict[str, Type[PromptSection]] = {}

    @classmethod
    def register(cls, section_cls: Type[PromptSection]) -> None:
        label = section_cls.label_static().lower()
        if not label or ":" not in label:
            raise ValueError(
                f"{section_cls.__name__} must define class attrs 'category' and 'name'"
            )
        cls._store[label] = section_cls

    @classmethod
    def get(cls, label: str) -> Optional[Type[PromptSection]]:
        return cls._store.get(label.lower())

    @classmethod
    def all(cls) -> Iterable[Type[PromptSection]]:
        return cls._store.values()

    @classmethod
    def clear(cls) -> None:
        cls._store.clear()