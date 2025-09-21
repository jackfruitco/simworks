# SimWorks/simai/promptkit/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Union


@dataclass(frozen=True)
class PromptContext:
    """
    Immutable context passed to all modifiers in the v2 pipeline.
    """
    user: Optional[Any] = None
    role: Optional[Any] = None
    simulation: Optional[Any] = None
    lab: Optional[str] = None

    include_defaults: bool = True
    include_history: bool = True
    strict: bool = False

    # Arbitrary extra inputs for modifiers
    payload: Dict[str, Any] = field(default_factory=dict)


MergeStrategy = Union[str, Callable[[str, str], str]]  # "first" | "last" | "concat" | callable


@dataclass
class PromptSection:
    """
    Uniform output unit produced by modifiers in the v2 pipeline.
    """
    id: str
    content: Union[str, List[str]]
    weight: int = 0
    tags: Set[str] = field(default_factory=set)
    merge: MergeStrategy = "concat"
    cache_key: Optional[str] = None

    def as_text(self) -> str:
        if isinstance(self.content, list):
            return "\n".join(self.content)
        return str(self.content or "").strip()
