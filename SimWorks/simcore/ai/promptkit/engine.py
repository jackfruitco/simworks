from __future__ import annotations

from typing import Iterable, Type, Union, Sequence
import asyncio
import logging

from .types import PromptSection, call_maybe_async, SectionOutput, Prompt


logger = logging.getLogger(__name__)

SectionSpec = Union[Type[PromptSection], PromptSection]


class PromptEngine:
    """
    Compose prompt sections and render them in weight order.

    Usage:
        prompt = await PromptEngine.abuild(BaseSection, Guardrails, **ctx)
        # or
        engine = PromptEngine(BaseSection).add(Guardrails)
        prompt = await engine.abuild(**ctx)
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
        logger.debug(f"...abuilding... [debug: {self.__class__.__name__[:20]} - {self._sections}]")
        ordered: Sequence[PromptSection] = sorted(
            self._sections, key=lambda s: (s.weight, s.label)
        )
        outputs: list[SectionOutput] = []
        used_labels: list[str] = []
        errors: list[dict] = []

        for sec in ordered:
            instr = None
            msg = None
            try:
                instr = await call_maybe_async(sec.render_instruction, **ctx)
            except Exception as e:
                logger.exception("Instruction render failed for %s", sec.label)
                errors.append({"label": sec.label, "stage": "instruction", "error": str(e)})
            try:
                msg = await call_maybe_async(sec.render_message, **ctx)
            except Exception as e:
                logger.exception("Message render failed for %s", sec.label)
                errors.append({"label": sec.label, "stage": "message", "error": str(e)})

            if (instr and instr.strip()) or (msg and msg.strip()):
                outputs.append(SectionOutput(instr, msg))
                used_labels.append(sec.label)

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


def merge_sections(outputs: list[SectionOutput]) -> Prompt:
    instr_parts = [o.instruction.strip() for o in outputs if o.instruction and o.instruction.strip()]
    msg_parts = [o.message.strip() for o in outputs if o.message and o.message.strip()]
    instruction = "\n\n".join(instr_parts)
    message = "\n\n".join(msg_parts) if msg_parts else None
    return Prompt(instruction=instruction, message=message)
