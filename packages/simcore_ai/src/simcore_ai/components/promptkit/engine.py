
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import is_dataclass, replace
from collections.abc import Iterable, Sequence
from typing import Type, Union

import logfire

from .base import PromptSection, Prompt
from .plans import PromptPlan
from simcore_ai.tracing import service_span, service_span_sync, flatten_context

logger = logging.getLogger(__name__)

SectionSpec = Union[Type[PromptSection], PromptSection]

__all__ = [
    "PromptEngine",
    "SectionSpec",
]


def _describe_section_spec(obj) -> dict:
    """Return a structured description of a section spec for logging.

    Designed for diagnostics when callers pass the wrong thing to the engine.
    Keeps this private to avoid coupling 'types' to logging concerns.
    """
    try:
        is_type = inspect.isclass(obj)
        cls = obj if is_type else type(obj)
        return {
            "is_instance": isinstance(obj, PromptSection),
            "is_type": is_type,
            "is_subclass": bool(is_type and issubclass(obj, PromptSection)),
            "class": f"{cls.__module__}.{getattr(cls, '__qualname__', cls.__name__)}",
            "repr": repr(obj)[:400],
        }
    except Exception as e:
        return {
            "error": f"{type(e).__name__}: {e}",
            "repr": repr(obj)[:400],
        }


def _section_key(sec: PromptSection) -> str:
    """Return a stable identity string for a section.

    Prefer the standardized Identity tuple3 (dot form). Fallback to a
    module-qualified class name only if Identity isn't available.
    """
    ident = getattr(sec, "identity", None)
    if ident is not None:
        to_str = getattr(ident, "to_string", None)
        if callable(to_str):
            try:
                return str(to_str())
            except Exception as e:
                logger.warning("identity.to_string() failed for %s: %s", type(sec).__name__, e)
    # Final fallback: module-qualified class name
    return f"{sec.__class__.__module__}.{sec.__class__.__name__}"


def _instantiate_with_overrides(
    section: SectionSpec, *, weight: int | None = None, tags: Iterable[str] | str | None = None
) -> PromptSection:
    """
    Create a PromptSection instance from a class or pass through an instance,
    then apply lightweight overrides (weight, tags) when provided. If overrides
    are requested and the section is a dataclass instance, a shallow clone is made
    to avoid mutating caller-owned instances.
    """
    inst = section() if isinstance(section, type) and issubclass(section, PromptSection) else section
    if not isinstance(inst, PromptSection):
        desc = _describe_section_spec(section)
        logger.error("Invalid section spec in _instantiate_with_overrides: %s", desc)
        raise TypeError(f"Sections must be PromptSection subclasses or instances; got {desc}")

    needs_clone = (weight is not None) or (tags is not None)
    new_inst = replace(inst) if (needs_clone and is_dataclass(inst)) else inst

    if weight is not None:
        try:
            new_inst.weight = int(weight)  # type: ignore[attr-defined]
        except Exception:
            logger.debug("Failed to apply weight override to %s", _section_key(new_inst))

    if tags is not None:
        try:
            if isinstance(tags, (str, bytes)):
                iter_tags = [tags]
            elif isinstance(tags, Iterable):
                iter_tags = list(tags)
            else:
                iter_tags = [tags]
            new_inst.tags = frozenset(str(t) for t in iter_tags)  # type: ignore[attr-defined]
        except Exception:
            logger.debug("Failed to apply tags override to %s", _section_key(new_inst))
    return new_inst


def _sections_from_plan(plan: "PromptPlan") -> list[PromptSection]:
    """
    Expand a PromptPlan into concrete PromptSection instances with any
    per-item overrides applied (weight, tags). Confidence data on the plan
    items is intentionally ignored here (no-op), but the structure remains
    for future use.
    """
    sections: list[PromptSection] = []
    for idx, item in enumerate(getattr(plan, "items", []) or []):
        try:
            section_obj = getattr(item, "section", None)
            weight = getattr(item, "weight", None) or getattr(item, "weight_override", None)
            tags = getattr(item, "tags", None)
            inst = _instantiate_with_overrides(section_obj, weight=weight, tags=tags)
            sections.append(inst)
        except Exception as e:
            logger.exception("Failed expanding plan item at index %s: %s", idx, e)
            # Re-raise to preserve current failure semantics (surfaced to service.ensure_prompt)
            raise
    return sections


class PromptEngine:
    """
    Compose prompt sections and render them in weight order.

    Usage:
        # Async (preferred in ASGI or when an event loop is running)
        prompt = await PromptEngine.abuild_from(plan=my_plan, **ctx)
        prompt = await PromptEngine.abuild_from(BaseSection, Guardrails, **ctx)
        prompt = await PromptEngine.abuild_from(BaseSection, plan=my_plan, **ctx)  # plan + overrides

        # Or build an instance explicitly
        engine = PromptEngine(BaseSection).add(Guardrails)
        prompt = await engine.abuild(**ctx)

        # Sync convenience (only when no event loop is running)
        prompt = PromptEngine.build_from(plan=my_plan, **ctx)
    """

    def __init__(self, *sections: SectionSpec):
        self._sections: list[PromptSection] = []
        self._seen: set[str] = set()
        if sections:
            self._add_many_sections(sections)

    def _merge_plan_sections(self, plan: "PromptPlan | None") -> tuple[int, int]:
        """
        Merge sections from a PromptPlan into this engine *without* overriding
        any already-added sections (explicit sections take precedence).

        Returns:
            (added, skipped) counts for diagnostics.
        """
        if plan is None:
            return (0, 0)
        added = 0
        skipped = 0
        # Expand plan into instances with overrides applied
        plan_sections = _sections_from_plan(plan)
        for sec in plan_sections:
            key = _section_key(sec)
            if key in self._seen:
                skipped += 1
                continue
            self._sections.append(sec)
            self._seen.add(key)
            added += 1
        return (added, skipped)

    # ----- configuration
    def _add_section(self, section: SectionSpec) -> "PromptEngine":
        inst = section() if isinstance(section, type) and issubclass(section, PromptSection) else section
        if not isinstance(inst, PromptSection):
            # Rich diagnostics to help find mistyped sections
            desc = _describe_section_spec(section)
            logger.error("Invalid section spec passed to PromptEngine.add: %s", desc)
            try:
                # Logfire may be absent/misconfigured; keep this non-fatal
                logfire.error("Invalid section spec passed to PromptEngine.add", extra={"section_spec": desc})
            except Exception:
                pass
            raise TypeError(f"Sections must be PromptSection subclasses or instances; got {desc}")
        key = _section_key(inst)
        if key not in self._seen:
            self._sections.append(inst)
            self._seen.add(key)
        return self

    def _add_many_sections(self, sections: Iterable[SectionSpec]) -> "PromptEngine":
        for idx, s in enumerate(sections):
            try:
                self._add_section(s)
            except TypeError:
                logger.error("add_many failed at index %d with spec: %s", idx, _describe_section_spec(s))
                try:
                    logfire.error(
                        "add_many failed",
                        extra={"index": idx, "section_spec": _describe_section_spec(s)},
                    )
                except Exception:
                    pass
                raise
        return self

    # ----- building
    async def abuild(self, **ctx) -> Prompt:
        # Avoid mutating caller’s dict
        ctx = dict(ctx)

        # Optionally merge a plan passed through context (async-first API).
        plan: PromptPlan | None = ctx.pop("plan", None)  # may be absent
        plan_added = 0
        plan_skipped = 0
        if plan is not None:
            plan_added, plan_skipped = self._merge_plan_sections(plan)
            # enrich tracing context with lightweight plan metadata
            try:
                plan_identity_str = getattr(getattr(plan, "identity", None), "to_string", lambda: None)()
                ctx.setdefault("prompt_plan.identity", plan_identity_str)
                ctx.setdefault("prompt_plan.item_count", len(getattr(plan, "items", []) or []))
                ctx.setdefault("prompt_plan.added", plan_added)
                ctx.setdefault("prompt_plan.skipped", plan_skipped)
            except Exception:
                pass

        _attrs = {
            "ai.section_count": len(self._sections),
            **flatten_context(ctx),
        }
        # annotate plan usage if present
        try:
            if ctx.get("prompt_plan.item_count") is not None:
                _attrs["ai.plan.used"] = True
                _attrs["ai.plan.items"] = int(ctx["prompt_plan.item_count"])
                if "prompt_plan.added" in ctx:
                    _attrs["ai.plan.added"] = int(ctx["prompt_plan.added"])
                if "prompt_plan.skipped" in ctx:
                    _attrs["ai.plan.skipped"] = int(ctx["prompt_plan.skipped"])
        except Exception:
            pass

        async with service_span("ai.prompt.build", attributes=_attrs):
            logger.debug(
                "PromptEngine.abuild: sections=%s",
                [_section_key(s) for s in self._sections],
            )
            # Preserve insertion order among sections with equal weight
            ordered: Sequence[PromptSection] = [
                s for _, s in sorted(
                    enumerate(self._sections),
                    key=lambda t: (t[1].weight, t[0], _section_key(t[1])),
                )
            ]
            outputs: list[tuple[str | None, str | None]] = []
            used_labels: list[str] = []
            errors: list[dict] = []

            for sec in ordered:
                async with service_span(
                    "ai.prompt.section",
                    attributes={
                        "ai.section": _section_key(sec),
                        "ai.category": getattr(sec, "category", None),
                        "ai.name": getattr(sec, "name", None),
                        "ai.weight": getattr(sec, "weight", None),
                        **flatten_context(ctx),
                    },
                ) as section_span:
                    instr = None
                    msg = None

                    # Render instruction
                    async with service_span(
                        "ai.prompt.render_instruction",
                        attributes={"ai.section": _section_key(sec), "ai.weight": getattr(sec, "weight", None), **flatten_context(ctx)},
                    ):
                        try:
                            instr = await sec.render_instruction(**ctx)
                        except Exception as e:
                            logger.exception("Instruction render failed for %s", _section_key(sec))
                            errors.append({"label": _section_key(sec), "stage": "instruction", "error": str(e)})

                    # Render message
                    async with service_span(
                        "ai.prompt.render_message",
                        attributes={"ai.section": _section_key(sec), "ai.weight": getattr(sec, "weight", None), **flatten_context(ctx)},
                    ):
                        try:
                            msg = await sec.render_message(**ctx)
                        except Exception as e:
                            logger.exception("Message render failed for %s", _section_key(sec))
                            errors.append({"label": _section_key(sec), "stage": "message", "error": str(e)})

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
                        used_labels.append(_section_key(sec))

            # Merge sections (sync span ok inside async)
            with service_span_sync(
                "ai.prompt.merge",
                attributes={
                    "ai.sections.used_count": len(used_labels),
                    "ai.sections.errors_count": len(errors),
                    **flatten_context(ctx),
                },
            ):
                prompt = _merge_sections(outputs)

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

    # ----- unified convenience (classmethods)
    @classmethod
    async def abuild_from(cls, *sections: SectionSpec, **ctx) -> Prompt:
        """
        Convenience async constructor that delegates to an instance's `abuild`.

        Any keyword-only context (including an optional `plan`) is forwarded
        to `abuild(**ctx)`.
        """
        return await cls(*sections).abuild(**ctx)

    @classmethod
    def build_from(cls, *sections: SectionSpec, **ctx) -> Prompt:
        """
        Convenience sync constructor that delegates to an instance's `build`.

        Only safe when no event loop is running.
        """
        return cls(*sections).build(**ctx)


def _merge_sections(outputs: list[tuple[str | None, str | None]]) -> Prompt:
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
