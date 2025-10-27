# simcore_ai/src/simcore_ai/promptkit/engine.py
from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Sequence
from typing import Type, Union

from .types import PromptSection, call_maybe_async, Prompt
from ..tracing import service_span, service_span_sync

logger = logging.getLogger(__name__)

SectionSpec = Union[Type[PromptSection], PromptSection]

__all__ = [
    "PromptEngine",
    "merge_sections",
    "SectionSpec",
]


class PromptEngine:
    """
    Compose prompt sections and render them in weight order.

    Usage:
        # Async (preferred in ASGI or when an event loop is running)
        prompt = await PromptEngine.abuild_from(BaseSection, Guardrails, **ctx)

        # Or build an instance explicitly
        engine = PromptEngine(BaseSection).add(Guardrails)
        prompt = await engine.abuild(**ctx)

        # Sync convenience (only when no event loop is running)
        prompt = PromptEngine.build_from(BaseSection, Guardrails, **ctx)
    """

    def __init__(self, *sections: SectionSpec):
        self._sections: list[PromptSection] = []
        self._seen: set[str] = set()
        if sections:
            self.add_many(sections)

    # ----- configuration
    def add(self, section: SectionSpec) -> "PromptEngine":
        inst = section() if isinstance(section, type) and issubclass(section, PromptSection) else section
        if not isinstance(inst, PromptSection):
            raise TypeError("Sections must be PromptSection subclasses or instances")
        if inst.label not in self._seen:
            self._sections.append(inst)
            self._seen.add(inst.label)
        return self

    def add_many(self, sections: Iterable[SectionSpec]) -> "PromptEngine":
        for s in sections:
            self.add(s)
        return self

    # ----- building
    async def abuild(self, **ctx) -> Prompt:
        async with service_span(
                "ai.prompt.build",
                attributes={"ai.section_count": len(self._sections)},
        ):
            logger.debug(f"...abuilding... [debug: {self.__class__.__name__[:20]} - {self._sections}]")
            # Preserve insertion order among sections with equal weight
            ordered: Sequence[PromptSection] = [
                s for _, s in sorted(
                    enumerate(self._sections),
                    key=lambda t: (t[1].weight, t[0], t[1].label),
                )
            ]
            outputs: list[tuple[str | None, str | None]] = []
            used_labels: list[str] = []
            errors: list[dict] = []

            for sec in ordered:
                async with service_span(
                        "ai.prompt.section",
                        attributes={
                            "ai.section": sec.label,
                            "ai.category": getattr(sec, "category", None),
                            "ai.name": getattr(sec, "name", None),
                            "ai.weight": getattr(sec, "weight", None),
                        },
                ) as section_span:
                    instr = None
                    msg = None

                    # Render instruction
                    async with service_span(
                            "ai.prompt.render_instruction",
                            attributes={"ai.section": sec.label, "ai.weight": getattr(sec, "weight", None)},
                    ):
                        try:
                            instr = await call_maybe_async(sec.render_instruction, **ctx)
                        except Exception as e:
                            logger.exception("Instruction render failed for %s", sec.label)
                            errors.append({"label": sec.label, "stage": "instruction", "error": str(e)})

                    # Render message
                    async with service_span(
                            "ai.prompt.render_message",
                            attributes={"ai.section": sec.label, "ai.weight": getattr(sec, "weight", None)},
                    ):
                        try:
                            msg = await call_maybe_async(sec.render_message, **ctx)
                        except Exception as e:
                            logger.exception("Message render failed for %s", sec.label)
                            errors.append({"label": sec.label, "stage": "message", "error": str(e)})

                    # Annotate the parent section span with outcomes
                    try:
                        section_span.set_attribute("ai.instruction.present", bool(instr and str(instr).strip()))
                        section_span.set_attribute("ai.message.present", bool(msg and str(msg).strip()))
                        if instr:
                            section_span.set_attribute("ai.instruction.len", len(instr))
                        if msg:
                            section_span.set_attribute("ai.message.len", len(msg))
                    except Exception:
                        pass

                    if (instr and instr.strip()) or (msg and msg.strip()):
                        outputs.append((instr, msg))
                        used_labels.append(sec.label)

            # Merge sections (sync span ok inside async)
            with service_span_sync(
                    "ai.prompt.merge",
                    attributes={
                        "ai.sections.used_count": len(used_labels),
                        "ai.sections.errors_count": len(errors),
                    },
            ):
                prompt = merge_sections(outputs)

            # Attach engine provenance to prompt meta without overwriting caller-supplied meta
            try:
                prompt.meta.setdefault("sections", used_labels)
                prompt.meta.setdefault("errors", errors)
            except Exception:
                # If meta isn't a dict for some reason, coerce safely
                prompt.meta = {"sections": used_labels, "errors": errors}
            return prompt

    def build(self, **ctx) -> Prompt:
        """
        Synchronous wrapper for abuild. Only safe when no loop is running.
        In ASGI/async contexts, call `await abuild(...)` instead.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.abuild(**ctx))
        raise RuntimeError(
            "PromptEngine.build() cannot run inside an active event loop. "
            "Use `await PromptEngine(...).abuild(**ctx)` instead."
        )

    # ----- convenience (classmethods)
    @classmethod
    async def abuild_from(cls, *sections: SectionSpec, **ctx) -> Prompt:
        return await cls(*sections).abuild(**ctx)

    @classmethod
    def build_from(cls, *sections: SectionSpec, **ctx) -> Prompt:
        return cls(*sections).build(**ctx)


def merge_sections(outputs: list[tuple[str | None, str | None]]) -> Prompt:
    """Merge section outputs into a single Prompt and annotate the current span.

    Returns
    -------
    Prompt
        A Prompt whose `instruction` is the concatenation of all non-empty section
        instructions (separated by blank lines). The `message` is the concatenation
        of all non-empty section messages, or `None` if there were none.

    Observability
    -------------
    Adds lightweight observability to the *current* span (if any):
      - ai.instruction.len / ai.message.len
      - ai.instruction.sha256 / ai.message.sha256
      - event: ai.prompt.preview (first 512 chars, truncated flag)
    """
    instr_parts = [(i or "").strip() for (i, _) in outputs if i and i.strip()]
    msg_parts = [(m or "").strip() for (_, m) in outputs if m and m.strip()]
    instruction = "\n\n".join(instr_parts)
    message = "\n\n".join(msg_parts) if msg_parts else None

    # Annotate the current span (if recording)
    try:
        from hashlib import sha256
        from opentelemetry import trace

        span = trace.get_current_span()
        # In some environments, a non-recording default span may be returned
        is_recording = getattr(span, "is_recording", lambda: False)()
        if is_recording:
            span.set_attribute("ai.instruction.len", len(instruction))
            span.set_attribute("ai.message.len", len(message) if message is not None else 0)
            span.set_attribute("ai.instruction.sha256", sha256(instruction.encode()).hexdigest())
            span.set_attribute("ai.message.sha256", sha256((message or "").encode()).hexdigest())

            # Optional truncated preview (512 chars cap)
            preview_instr = instruction[:512]
            preview_msg = (message or "")[:512]
            span.add_event(
                "ai.prompt.preview",
                {
                    "instruction.preview": preview_instr,
                    "message.preview": preview_msg,
                    "truncated": bool(len(instruction) > 512 or (len(message or "") > 512)),
                },
            )
    except Exception:
        # Never let observability break prompt building
        pass

    return Prompt(instruction=instruction, message=message)
