# simcore_ai/promptkit/types.py
from __future__ import annotations
"""
Core promptkit types (AIv3).

This module defines lightweight types shared by the prompt system:

- `Prompt`: final aggregate produced by a prompt engine. Services convert this
  to LLMRequestMessage objects (default: developer instruction + user message).
- `PromptSection`: declarative section base class. Sections advertise identity
  via a class-level `identity: Identity`. The canonical identity string uses
  dot form: `namespace.kind.name`.
- `context` (on `Prompt`): a plain dict passed through by services/engines so
  downstream layers (runner/client/provider) can enrich telemetry or perform
  app-specific logic without coupling. The core does not interpret these keys.

Backward compatibility with legacy `namespace` or colon identities is removed.

Empty instruction + message is allowed at this layer (engines may merge many
sections); services/runners enforce the "not-both-empty" rule before providers.
"""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Optional
import logging

from simcore_ai.identity import Identity

logger = logging.getLogger(__name__)

PROMPT_VERSION = 3

__all__ = [
    "PROMPT_VERSION",
    "Prompt",
    "PromptSection",
    "Renderable",
    "ConfidenceNote",
]


# ---------------- Prompt (final aggregate) --------------------------------

@dataclass(slots=True)
class Prompt:
    """Final prompt object produced by the engine and consumed by services.

    Attributes:
        instruction: Developer/system guidance for the model (maps to role="developer").
        message: End-user message for the model (maps to role="user").
        extra_messages: Optional list of (role, text) pairs for additional context.
        context: Arbitrary context carried alongside the prompt (propagated to tracing).
        meta: Arbitrary metadata for traceability/debugging.
    """
    instruction: str = ""
    message: Optional[str] = None
    extra_messages: list[tuple[str, str]] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.instruction = (self.instruction or "").strip()
        if self.message is not None:
            self.message = self.message.strip()
        # basic normalization for extras
        self.extra_messages = [
            (str(role), str(text))
            for role, text in (self.extra_messages or [])
            if str(text).strip()
        ]
        # ensure context is a shallow dict for safe propagation
        if not isinstance(self.context, dict):
            try:
                self.context = dict(self.context)  # type: ignore[arg-type]
            except Exception:
                self.context = {}
        self.meta.setdefault("version", PROMPT_VERSION)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruction": self.instruction,
            "message": self.message,
            "extra_messages": list(self.extra_messages),
            "context": dict(self.context),
            "meta": dict(self.meta),  # shallow copy to avoid external mutation
        }

    def with_context(self, **more: Any) -> "Prompt":
        """Return a new Prompt with context updated by `more` (shallow copy)."""
        new_ctx = dict(self.context)
        new_ctx.update(more)
        return Prompt(
            instruction=self.instruction,
            message=self.message,
            extra_messages=list(self.extra_messages),
            context=new_ctx,
            meta=dict(self.meta),
        )

    def has_content(self) -> bool:
        """Return True if either instruction or message has non-empty text."""
        return bool(self.instruction) or bool(self.message)


# Used by render methods and helpers.
Renderable = str | None | Awaitable[str | None]


# ---------------- Confidence plumbing (not used yet; safe to add) --------

@dataclass(slots=True)
class ConfidenceNote:
    """Optional confidence signal a section can expose for future planners.

    score: 0.0..1.0 (advisory weight; not a probability)
    note: short human-readable explanation for debugging
    """
    score: float
    note: str = ""


# ---------------- Section base -------------------------------------------

@dataclass(order=True, slots=True)
class PromptSection:
    """Base class for declarative prompt sections (AIv3).

    Sections provide identity **at the class level** using:
      • `identity: Identity`  (required).

    Instances may also carry static `instruction`/`message` text, which an
    engine may use directly when present.

    The canonical identity string is dot-based: `namespace.kind.name`.

    Subclasses may optionally override `assess_confidence(context=...)` to
    provide an advisory ConfidenceNote for future auto-planners. This is not
    invoked by core today; it’s here to keep section signatures stable.
    """

    # sort key first (dataclass(order=True) sorts by this)
    weight: int = field(default=100, compare=True)

    # optional static content (instance- or class-level)
    instruction: Optional[str] = field(default=None, compare=False)
    message: Optional[str] = field(default=None, compare=False)

    # optional tags (non-functional; for selection or debugging)
    tags: frozenset[str] = field(default_factory=frozenset, compare=False, repr=False)

    def __repr__(self) -> str:
        return f"<PromptSection {self.identity_str} tags={self.tags or 'None'}>"

    # ---------------- Identity helpers (class + instance) -----------------
    @classmethod
    def get_cls_identity(cls) -> Identity:
        """Return the class identity as an `Identity`.

        A class-level `identity: Identity` attribute is required.

        Raises:
            TypeError: if identity cannot be derived.
        """
        ident = getattr(cls, "identity", None)
        if isinstance(ident, Identity):
            return ident
        raise TypeError(
            f"{cls.__name__} must define a class-level `identity: Identity`. "
            f"The legacy `namespace/kind/name` attributes are no longer supported."
        )

    @property
    def identity(self) -> Identity:
        """Instance view of the class identity."""
        return type(self).get_cls_identity()

    @property
    def identity_str(self) -> str:
        """Canonical dot identity string (e.g., 'chatlab.patient.initial')."""
        return self.identity.to_string()

    # ---------------- Rendering helpers ----------------------------------
    async def render_instruction(self, **ctx: Any) -> str | None:
        """Return developer/system instructions for this section, if any."""
        text = self.instruction if self.instruction is not None else getattr(type(self), "instruction", None)
        out = _normalize(text)
        logger.debug("promptkit.render_instruction: ident=%s present=%s", self.identity_str, bool(out))
        return out

    async def render_message(self, **ctx: Any) -> str | None:
        """Return end-user message content for this section, if any."""
        text = self.message if self.message is not None else getattr(type(self), "message", None)
        out = _normalize(text)
        logger.debug("promptkit.render_message: ident=%s present=%s", self.identity_str, bool(out))
        return out

    # ---------------- Confidence (advisory; optional) ---------------------
    async def assess_confidence(self, *, context: dict[str, Any]) -> ConfidenceNote | None:  # pragma: no cover
        """Optional advisory signal for future planners. Not used in core yet."""
        return None


# ---------------- Utilities ----------------------------------------------

def _normalize(out: str | None) -> str | None:
    if out is None:
        return None
    s = str(out).strip()
    return s or None