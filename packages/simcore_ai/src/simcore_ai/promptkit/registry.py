# simcore_ai/promptkit/registry.py
from __future__ import annotations

from typing import Iterable, Type
import logging
import threading
from .types import PromptSection


class PromptRegistry:
    """
    Global store mapping label -> PromptSection subclass.
    We store CLASSES (not instances) so they can carry behavior.
    """
    _store: dict[str, Type[PromptSection]] = {}
    _lock = threading.RLock()

    @classmethod
    def register(cls, section_cls: Type[PromptSection]) -> None:
        label = section_cls.label_static().lower()
        if not label or ":" not in label:
            raise ValueError(
                f"{section_cls.__name__} must define class attrs 'category' and 'name'"
            )
        with cls._lock:
            if label in cls._store:
                logging.getLogger(__name__).warning(
                    "PromptRegistry overwriting existing section for label '%s' with %s",
                    label,
                    section_cls.__name__,
                )
            cls._store[label] = section_cls

    @classmethod
    def get(cls, label: str) -> Type[PromptSection] | None:
        with cls._lock:
            return cls._store.get(label.lower())

    @classmethod
    def all(cls) -> Iterable[Type[PromptSection]]:
        with cls._lock:
            return tuple(cls._store.values())

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._store.clear()


def register_section(section_cls: Type[PromptSection]) -> Type[PromptSection]:
    """Decorator to register a PromptSection class in the global registry."""
    PromptRegistry.register(section_cls)
    return section_cls

def get_by_category_name(category: str, name: str) -> Type[PromptSection] | None:
    """Helper to fetch a section by explicit category/name."""
    label = f"{(category or '').strip().lower()}:{(name or '').strip().lower()}"
    return PromptRegistry.get(label)