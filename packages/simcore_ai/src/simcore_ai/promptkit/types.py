# simcore_ai/promptkit/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable
import inspect
import logging

logger = logging.getLogger(__name__)

PROMPT_VERSION = 3

__all__ = [
    "PROMPT_VERSION",
    "Prompt",
    "PromptSection",
    "Renderable",
    "call_maybe_async",
]

@dataclass
class Prompt:
    """Final prompt object produced by the engine and passed to the LLM.
    - instruction: developer/system guidance for the model
    - message: end-user message (what the "user" says)
    Additional metadata can be attached in `meta`.
    """
    instruction: str = ""
    message: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.instruction = (self.instruction or "").strip()
        if self.message is not None:
            self.message = self.message.strip()
        self.meta.setdefault("version", PROMPT_VERSION)

    def to_dict(self):
        return {
            "instruction": self.instruction,
            "message": self.message,
            "meta": dict(self.meta),  # shallow copy to avoid external mutation
        }

Renderable = str | None | Awaitable[str | None]

@dataclass(order=True)
class PromptSection:
    """
    Base class for declarative prompt sections.
    Subclasses typically override class attrs (category, name, weight)
    and implement `render(self, **ctx) -> str|None|Awaitable[str|None]`.
    """
    # sort key first (dataclass(order=True) sorts by this)
    weight: int = field(default=100, compare=True)

    # identity
    category: str = field(default="", compare=False)
    name: str = field(default="", compare=False)

    # optional static content
    # `instruction` is used for LLM developer/system instructions
    # `message` is used for LLM end-user messages
    instruction: str | None = field(default=None, compare=False)
    message: str | None = field(default=None, compare=False)

    # optional tags
    tags: frozenset[str] = field(default_factory=frozenset, compare=False, repr=False)

    # ---- labeling helpers
    @property
    def label(self) -> str:
        cat = (self.category or getattr(type(self), "category", "") or "").strip().lower()
        nam = (self.name or getattr(type(self), "name", "") or "").strip().lower()
        return f"{cat}:{nam}"

    @classmethod
    def label_static(cls) -> str:
        cat = (getattr(cls, "category", "") or "").strip().lower()
        nam = (getattr(cls, "name", "") or "").strip().lower()
        return f"{cat}:{nam}"

    # ---- rendering
    async def render_instruction(self, **ctx) -> str | None:
        """Return developer/system instructions for this section, if any."""
        logger.debug("Render instruction: %s (has=%s)", self.label, self.instruction is not None)
        text = self.instruction if self.instruction is not None else getattr(type(self), "instruction", None)
        return _normalize(text)

    async def render_message(self, **ctx) -> str | None:
        """Return end-user message content for this section, if any."""
        logger.debug("Render message: %s (has=%s)", self.label, self.message is not None)
        text = self.message if self.message is not None else getattr(type(self), "message", None)
        return _normalize(text)

    async def render(self, **ctx) -> str | None:
        """Backward-compat: treat as instruction render by default."""
        return await self.render_instruction(**ctx)


def _normalize(out: str | None) -> str | None:
    if out is None:
        logger.debug("Normalize: None -> None")
        return None
    s = str(out).strip()
    logger.debug("Normalize: %s...", s[:300])
    return s or None


async def call_maybe_async(fn: Callable[..., Renderable], *args, **kwargs) -> str | None:
    """
    Await fn if it’s an async function or returns an awaitable.
    Return normalized str|None, logging and swallowing exceptions safely.
    """
    try:
        if inspect.iscoroutinefunction(fn):
            return _normalize(await fn(*args, **kwargs))
        res = fn(*args, **kwargs)
        if inspect.isawaitable(res):  # defensive: someone returned a coroutine
            return _normalize(await res)
        return _normalize(res)
    except Exception as e:
        logger.warning("Prompt section call failed for %s: %s", getattr(fn, "__name__", fn), e, exc_info=True)
        return None
