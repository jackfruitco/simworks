import asyncio
import inspect
import logging
from collections.abc import Iterable, Sequence
from dataclasses import is_dataclass, replace
from typing import Type, Union

import logfire

from orchestrai.tracing import service_span, service_span_sync, flatten_context
from .base import PromptSection, Prompt
from .plans import PromptPlan
from ...identity.exceptions import IdentityError

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


def _get_section_label(sec: PromptSection) -> str:
    """
    Return a stable identity label for a section.

    Preference order:
      1. `identity.label` (canonical string form)
      2. `identity.as_str` (canonical dot form)
      3. `str(identity)` as a last resort

    Raises
    ------
    IdentityError
        If no identity is attached or the identity object cannot be stringified.
    """
    ident = getattr(type(sec), "identity", None) or getattr(sec, "identity", None)
    if ident is None:
        raise IdentityError(
            f"Missing identity for section {type(sec).__name__}. "
            "Does the component include the IdentityMixin?"
        )

    label_attr = getattr(ident, "label", None)
    if isinstance(label_attr, str):
        return label_attr

    raise IdentityError(
        f"Could not derive identity label for section {type(sec).__name__}: "
        "identity object has no `label` string attribute"
    )


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
            try:
                label = _get_section_label(new_inst)
            except Exception:
                label = repr(new_inst)
            logger.debug("Failed to apply weight override to %s", label)

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
            try:
                label = _get_section_label(new_inst)
            except Exception:
                label = repr(new_inst)
            logger.debug("Failed to apply tags override to %s", label)
    return new_inst


def _sections_from_plan(plan: "PromptPlan") -> list[PromptSection]:
    """
    Expand a PromptPlan into concrete PromptSection instances.

    Supports both:
      - Plan items that expose `.section`, `.weight` (or `.weight_override` / `.order` for backward-compat), `.tags`, etc.
      - Raw SectionSpec entries (PromptSection subclasses or instances).

    Per-item overrides (weight, tags) are applied when present; confidence
    metadata is intentionally ignored here (no-op), but the structure remains
    for future use.
    """
    sections: list[PromptSection] = []
    for idx, item in enumerate(getattr(plan, "items", []) or []):
        try:
            # Support both "plan items" with .section and raw SectionSpec entries
            section_obj = getattr(item, "section", None) or item
            weight = (
                getattr(item, "weight", None)
                or getattr(item, "weight_override", None)
                or getattr(item, "order", None)
            )
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
    Compose prompt sections and render them in order order.

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
            return 0, 0
        added = 0
        skipped = 0
        # Expand plan into instances with overrides applied
        plan_sections = _sections_from_plan(plan)
        for sec in plan_sections:
            key = _get_section_label(sec)
            if key in self._seen:
                skipped += 1
                continue
            self._sections.append(sec)
            self._seen.add(key)
            added += 1
        return added, skipped

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
        key = _get_section_label(inst)
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

    # ----- public configuration (fluent) -----
    def add(self, section: SectionSpec) -> "PromptEngine":
        """
        Add a single section (class or instance) to the engine.

        This is a public wrapper around `_add_section` and supports fluent
        chaining, e.g.:

            engine = PromptEngine(BaseSection).add(Guardrails)
        """
        return self._add_section(section)

    def add_many(self, sections: Iterable[SectionSpec]) -> "PromptEngine":
        """
        Add multiple sections to the engine in order.

        This is a public wrapper around `_add_many_sections` primarily for
        ergonomic/fluent usage.
        """
        return self._add_many_sections(sections)

    # ----- building
    async def abuild(self, **ctx) -> Prompt:
        """
        Build a Prompt from the configured sections and an optional PromptPlan.

        This is the async-first entrypoint; in ASGI or any environment with
        an active event loop, prefer this over `build()`.
        """
        # Avoid mutating caller’s dict
        ctx = dict(ctx)

        # Lightweight visibility into what we're about to do
        try:
            section_labels = [_get_section_label(s) for s in self._sections]
        except Exception:
            section_labels = []
        logger.info(
            "PromptEngine.abuild: starting with %d sections",
            len(self._sections),
        )
        logger.debug("PromptEngine.abuild: section labels=%s", section_labels)

        # Optionally merge a plan passed through context (async-first API).
        plan: PromptPlan | None = ctx.pop("plan", None)  # may be absent
        plan_added = 0
        plan_skipped = 0
        if plan is not None:
            plan_added, plan_skipped = self._merge_plan_sections(plan)
            # Enrich tracing context with lightweight plan metadata
            try:
                plan_identity = getattr(plan, "identity", None)
                plan_identity_str: str | None = None
                if plan_identity is not None:
                    label_attr = getattr(plan_identity, "label", None)
                    if isinstance(label_attr, str):
                        plan_identity_str = label_attr
                    else:
                        as_str_attr = getattr(plan_identity, "as_str", None)
                        if isinstance(as_str_attr, str):
                            plan_identity_str = as_str_attr
                        else:
                            plan_identity_str = str(plan_identity)

                item_count = len(getattr(plan, "items", []) or [])

                ctx.setdefault("prompt_plan.identity", plan_identity_str)
                ctx.setdefault("prompt_plan.item_count", item_count)
                ctx.setdefault("prompt_plan.added", plan_added)
                ctx.setdefault("prompt_plan.skipped", plan_skipped)

                logger.info(
                    "PromptEngine: merged PromptPlan(identity=%r, items=%s, added=%s, skipped=%s)",
                    plan_identity_str,
                    item_count,
                    plan_added,
                    plan_skipped,
                )
            except Exception:
                logger.debug(
                    "PromptEngine: failed to attach plan metadata to context",
                    exc_info=True,
                )

        _attrs = {
            "orchestrai.section_count": len(self._sections),
            **flatten_context(ctx),
        }
        # annotate plan usage if present
        try:
            if ctx.get("prompt_plan.item_count") is not None:
                _attrs["orchestrai.plan.used"] = True
                _attrs["orchestrai.plan.items"] = int(ctx["prompt_plan.item_count"])
                if "prompt_plan.added" in ctx:
                    _attrs["orchestrai.plan.added"] = int(ctx["prompt_plan.added"])
                if "prompt_plan.skipped" in ctx:
                    _attrs["orchestrai.plan.skipped"] = int(ctx["prompt_plan.skipped"])
        except Exception:
            pass

        async with service_span("orchestrai.prompt.build", attributes=_attrs):
            logger.debug(
                "PromptEngine.abuild: sections=%s",
                [_get_section_label(s) for s in self._sections],
            )
            # Preserve insertion order among sections with equal weight
            ordered: Sequence[PromptSection] = [
                s
                for _, s in sorted(
                    enumerate(self._sections),
                    key=lambda t: (getattr(t[1], "weight", 100), t[0], _get_section_label(t[1])),
                )
            ]
            outputs: list[tuple[str | None, str | None]] = []
            used_labels: list[str] = []
            errors: list[dict] = []

            for sec in ordered:
                # Resolve label once per section for consistent logging/tracing
                label = _get_section_label(sec)

                async with service_span(
                        "orchestrai.prompt.section",
                        attributes={
                            "orchestrai.section": label,
                            "orchestrai.category": getattr(sec, "category", None),
                            "orchestrai.name": getattr(sec, "name", None),
                            "orchestrai.weight": getattr(sec, "weight", None),
                            **flatten_context(ctx),
                        },
                ) as section_span:
                    instr = None
                    msg = None

                    # Render instruction
                    async with service_span(
                            "orchestrai.prompt.render_instruction",
                            attributes={
                                "orchestrai.section": label,
                                "orchestrai.weight": getattr(sec, "weight", None),
                                **flatten_context(ctx),
                            },
                    ):
                        try:
                            logger.debug("PromptEngine: rendering instruction for %s", label)
                            instr = await sec.render_instruction(**ctx)
                        except Exception as e:
                            logger.exception("Instruction render failed for %s", label)
                            errors.append({"label": label, "stage": "instruction", "error": str(e)})

                    # Render message
                    async with service_span(
                            "orchestrai.prompt.render_message",
                            attributes={
                                "orchestrai.section": label,
                                "orchestrai.weight": getattr(sec, "weight", None),
                                **flatten_context(ctx),
                            },
                    ):
                        try:
                            logger.debug("PromptEngine: rendering message for %s", label)
                            msg = await sec.render_message(**ctx)
                        except Exception as e:
                            logger.exception("Message render failed for %s", label)
                            errors.append({"label": label, "stage": "message", "error": str(e)})

                    # Annotate the parent section span with outcomes
                    try:
                        section_span.set_attribute("orchestrai.instruction.present", bool(instr and str(instr).strip()))
                        section_span.set_attribute("orchestrai.message.present", bool(msg and str(msg).strip()))
                        if instr:
                            section_span.set_attribute("orchestrai.instruction.len", len(instr))
                        if msg:
                            section_span.set_attribute("orchestrai.message.len", len(msg))
                    except Exception:
                        pass

                    if (instr and instr.strip()) or (msg and msg.strip()):
                        outputs.append((instr, msg))
                        used_labels.append(label)
                        logger.info("PromptEngine: section %s contributed to prompt", label)

            # Merge sections (sync span ok inside async)
            with service_span_sync(
                    "orchestrai.prompt.merge",
                    attributes={
                        "orchestrai.sections.used_count": len(used_labels),
                        "orchestrai.sections.errors_count": len(errors),
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
    """Merge section output into a single Prompt and annotate the current span.

    Returns
    -------
    Prompt
        A Prompt whose `instruction` is the concatenation of all non-empty section
        instructions (separated by blank lines). The `message` is the concatenation
        of all non-empty section input, or `None` if there were none.

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
            span.set_attribute("orchestrai.instruction.len", len(instruction))
            span.set_attribute("orchestrai.message.len", len(message) if message is not None else 0)
            span.set_attribute("orchestrai.instruction.sha256", sha256(instruction.encode()).hexdigest())
            span.set_attribute("orchestrai.message.sha256", sha256((message or "").encode()).hexdigest())

            # Optional truncated preview (512 chars cap)
            preview_instr = instruction[:512]
            preview_msg = (message or "")[:512]
            span.add_event(
                "orchestrai.prompt.preview",
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
