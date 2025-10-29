# simcore_ai/promptkit/types.py
from __future__ import annotations

"""Core promptkit types (AIv3).

This module defines lightweight types shared by the prompt system:

- `Prompt`: final aggregate produced by a prompt engine. Services convert this
  to LLMRequestMessage objects (default: developer instruction + user message).
- `PromptSection`: declarative section base class. Sections advertise identity
  via either a class-level `identity: Identity` or class attrs `namespace/kind/name`.
  The canonical identity string uses **dot form**: `namespace.kind.name`.

Backward compatibility with legacy `namespace` or colon identities is removed.

Empty instruction + message is allowed at this layer (engines may merge many sections); services/runners enforce the "not-both-empty" rule before calling providers.
"""

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Awaitable, Optional
import inspect
import logging

from simcore_ai.identity import Identity

logger = logging.getLogger(__name__)

PROMPT_VERSION = 3

__all__ = [
    "PROMPT_VERSION",
    "Prompt",
    "PromptSection",
    "Renderable",
    "call_maybe_async",
]


@dataclass(slots=True)
class Prompt:
    """Final prompt object produced by the engine and consumed by services.

    Attributes:
        instruction: Developer/system guidance for the model (maps to role="developer").
        message: End-user message for the model (maps to role="user").
        extra_messages: Optional list of (role, text) pairs for additional context.
        meta: Arbitrary metadata for traceability/debugging.
    """

    instruction: str = ""
    message: Optional[str] = None
    extra_messages: list[tuple[str, str]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.instruction = (self.instruction or "").strip()
        if self.message is not None:
            self.message = self.message.strip()
        # basic normalization for extras
        self.extra_messages = [
            (str(role), str(text)) for role, text in (self.extra_messages or []) if str(text).strip()
        ]
        self.meta.setdefault("version", PROMPT_VERSION)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruction": self.instruction,
            "message": self.message,
            "extra_messages": list(self.extra_messages),
            "meta": dict(self.meta),  # shallow copy to avoid external mutation
        }

    def has_content(self) -> bool:
        """Return True if either instruction or message has non-empty text."""
        return bool(self.instruction) or bool(self.message)


# Used by render methods and helpers.
Renderable = str | None | Awaitable[str | None]


@dataclass(order=True, slots=True)
class PromptSection:
    """Base class for declarative prompt sections (AIv3).

    Sections provide identity **at the class level** using one of:
      1) `identity: Identity` (preferred), or
      2) `namespace`, `kind`, and `name` string attributes.

    Instances may also carry static `instruction`/`message` text, which the
    engine may use directly when present.

    The canonical identity string is **dot-based**: `namespace.kind.name`.
    """

    # sort key first (dataclass(order=True) sorts by this)
    weight: int = field(default=100, compare=True)

    # optional static content (instance- or class-level)
    instruction: Optional[str] = field(default=None, compare=False)
    message: Optional[str] = field(default=None, compare=False)

    # optional tags (non-functional; for selection or debugging)
    tags: frozenset[str] = field(default_factory=frozenset, compare=False, repr=False)

    # ---------------- Identity helpers (class + instance) -----------------
    @classmethod
    def identity_static(cls) -> Identity:
        """Return the class identity as an `Identity`.

        Resolution order:
          1) class attr `identity: Identity`
          2) class attrs `namespace`, `kind`, `name` (all truthy strings)

        Raises:
            TypeError: if identity cannot be derived.
        """
        ident = getattr(cls, "identity", None)
        if isinstance(ident, Identity):
            return ident

        namespace = getattr(cls, "namespace", None)
        kind = getattr(cls, "kind", None)
        name = getattr(cls, "name", None)
        if all(isinstance(x, str) and x for x in (namespace, kind, name)):
            return Identity.from_parts(namespace=namespace, kind=kind, name=name)

        raise TypeError(
            f"{cls.__name__} must define either `identity: Identity` or class attrs "
            f"`namespace`, `kind`, and `name`.")

    @property
    def identity(self) -> Identity:
        """Instance view of the class identity."""
        return type(self).identity_static()

    @property
    def identity_str(self) -> str:
        """Canonical dot identity string (e.g., "chatlab.patient.initial")."""
        return self.identity.to_string()

    # ---------------- Rendering helpers ----------------------------------
    async def render_instruction(self, **ctx: Any) -> str | None:
        """Return developer/system instructions for this section, if any."""
        text = self.instruction if self.instruction is not None else getattr(type(self), "instruction", None)
        out = _normalize(text)
        logger.debug("Render instruction: %s (present=%s)", self.identity_str, bool(out))
        return out

    async def render_message(self, **ctx: Any) -> str | None:
        """Return end-user message content for this section, if any."""
        text = self.message if self.message is not None else getattr(type(self), "message", None)
        out = _normalize(text)
        logger.debug("Render message: %s (present=%s)", self.identity_str, bool(out))
        return out

    async def render(self, **ctx: Any) -> str | None:
        """Backward-compat shim: default to instruction rendering (deprecated)."""
        return await self.render_instruction(**ctx)


# ---------------- Utilities ----------------------------------------------

def _normalize(out: str | None) -> str | None:
    if out is None:
        return None
    s = str(out).strip()
    return s or None


async def call_maybe_async(fn: Callable[..., Renderable], *args: Any, **kwargs: Any) -> str | None:
    """Call `fn`, awaiting if necessary, and normalize the return to `str|None`.

    This helper is resilient to accidental coroutine returns and logs failures
    without raising, returning `None` instead.
    """
    try:
        if inspect.iscoroutinefunction(fn):
            return _normalize(await fn(*args, **kwargs))
        res = fn(*args, **kwargs)
        if inspect.isawaitable(res):  # defensive: someone returned a coroutine
            return _normalize(await res)
        return _normalize(res)
    except Exception as e:  # pragma: no cover - never break rendering
        logger.warning("Prompt section call failed for %s: %s", getattr(fn, "__name__", fn), e, exc_info=True)
        return None
