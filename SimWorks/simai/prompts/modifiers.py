# SimWorks/simai/promptkit/modifiers.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from .types import PromptContext, PromptSection

# Phase order for planning and deterministic execution
PHASE_ORDER: List[str] = [
    "defaults",
    "persona",
    "lab",
    "history",
    "task",
    "safety",
    "render",
]


@dataclass
class ModifierMeta:
    key: str
    func: Callable[[PromptContext], Awaitable[Optional[PromptSection]]]
    phase: str = "task"
    requires: Set[str] = field(default_factory=set)
    provides: Set[str] = field(default_factory=set)
    default: bool = False
    priority: int = 0
    tags: Set[str] = field(default_factory=set)


# In-memory registry for v2 modifiers
_MODIFIERS_V2: Dict[str, ModifierMeta] = {}


def modifier(
    *,
    key: str,
    phase: str = "task",
    requires: Optional[Set[str]] = None,
    provides: Optional[Set[str]] = None,
    default: bool = False,
    priority: int = 0,
    tags: Optional[Set[str]] = None,
):
    """
    Decorator to register a v2 modifier with metadata.
    """

    def decorator(func: Callable[[PromptContext], Awaitable[Optional[PromptSection]]]):
        k = key.casefold()
        if k in _MODIFIERS_V2:
            raise ValueError(f"Modifier '{key}' is already registered (v2).")
        meta = ModifierMeta(
            key=k,
            func=func,
            phase=phase,
            requires=set(requires or []),
            provides=set(provides or []),
            default=default,
            priority=priority,
            tags=set(tags or []),
        )
        _MODIFIERS_V2[k] = meta
        return func

    return decorator


def get_modifier(key: str) -> Optional[ModifierMeta]:
    return _MODIFIERS_V2.get(key.casefold())


def list_modifiers() -> List[ModifierMeta]:
    return list(_MODIFIERS_V2.values())


__all__ = [
    "modifier",
    "get_modifier",
    "list_modifiers",
    "PHASE_ORDER",
    "ModifierMeta",
]
