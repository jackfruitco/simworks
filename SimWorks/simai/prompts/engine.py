# SimWorks/simai/promptkit/engine.py
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .types import PromptContext, PromptSection
from .modifiers import list_modifiers, PHASE_ORDER, ModifierMeta

logger = logging.getLogger(__name__)

# Ensure built-in v2 modifiers are registered upon import
try:
    from . import builtin_v2  # noqa: F401
except Exception as e:
    logger.debug(f"v2 builtins import error (can be safe during migrations): {e}")


class PlanningError(RuntimeError):
    pass


def _normalize_recipe(recipe: Optional[Iterable[str]]) -> List[str]:
    items: List[str] = []
    for it in recipe or []:
        if not isinstance(it, str):
            raise PlanningError(f"Recipe items must be keys (str); got: {type(it)}")
        items.append(it.casefold())
    # de-dupe preserving order
    seen: Set[str] = set()
    out: List[str] = []
    for k in items:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _phase_index(phase: str) -> int:
    try:
        return PHASE_ORDER.index(phase)
    except ValueError:
        return len(PHASE_ORDER)


def _plan(ctx: PromptContext, recipe: Optional[Iterable[str]]) -> Tuple[List[str], Dict[str, ModifierMeta]]:
    """
    Build a simple ordered plan:
    - normalize recipe
    - auto-include lab and defaults
    - validate keys, expand 'requires'
    - sort by (phase, priority, original order)
    """
    requested = _normalize_recipe(recipe)
    registry: Dict[str, ModifierMeta] = {m.key: m for m in list_modifiers()}

    # remember first-seen order for stable sorting
    order_index: Dict[str, int] = {k: i for i, k in enumerate(requested)}

    # Auto-include lab if present
    if ctx.lab:
        lab_key = f"lab.{ctx.lab}".casefold()
        if lab_key in registry and lab_key not in requested:
            order_index[lab_key] = len(order_index)
            requested.append(lab_key)

    # Include defaults
    if ctx.include_defaults:
        for m in registry.values():
            if m.default and m.key not in requested:
                order_index[m.key] = len(order_index)
                requested.append(m.key)

    # If history disabled, drop default history-phase items
    if not ctx.include_history:
        requested = [
            k for k in requested
            if not (k in registry and registry[k].phase == "history" and registry[k].default)
        ]

    # Validate and collect metas
    metas: Dict[str, ModifierMeta] = {}
    missing: List[str] = []
    for k in requested:
        if k in registry:
            metas[k] = registry[k]
        else:
            missing.append(k)

    if missing:
        msg = f"Unknown modifiers in recipe: {missing}"
        if ctx.strict:
            raise PlanningError(msg)
        logger.warning(msg + " (ignored)")
        requested = [k for k in requested if k in metas]

    # Expand dependencies (transitively)
    changed = True
    guard = 0
    while changed and guard < 1000:
        changed = False
        guard += 1
        for k in list(metas.keys()):
            reqs = metas[k].requires
            for req in reqs:
                if req in metas:
                    continue
                if req in registry:
                    metas[req] = registry[req]
                    if req not in requested:
                        order_index[req] = len(order_index)
                        requested.append(req)
                    changed = True
                else:
                    msg = f"Missing required dependency '{req}' for '{k}'"
                    if ctx.strict:
                        raise PlanningError(msg)
                    logger.warning(msg + " (ignored)")

    # Final sort by (phase, priority, original order index, key)
    def sort_key(k: str):
        m = metas[k]
        return (_phase_index(m.phase), m.priority, order_index.get(k, 1_000_000), k)

    ordered = sorted([k for k in requested if k in metas], key=sort_key)
    return ordered, metas


def _merge(existing: Optional[PromptSection], incoming: PromptSection) -> PromptSection:
    if not existing:
        return incoming

    strategy = incoming.merge or "concat"
    if callable(strategy):
        existing.content = strategy(existing.as_text(), incoming.as_text())
        return existing

    if strategy == "first":
        return existing
    if strategy == "last":
        return incoming

    # default "concat"
    e = existing.as_text()
    i = incoming.as_text()
    sep = "\n\n" if e and i else ""
    existing.content = e + sep + i
    return existing


async def _execute_all(ordered: List[str], metas: Dict[str, ModifierMeta], ctx: PromptContext) -> List[PromptSection]:
    """
    Execute all modifiers concurrently; merge results in planned order.
    """
    tasks = [metas[k].func(ctx) for k in ordered]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    collected: Dict[str, PromptSection] = {}

    for k, result in zip(ordered, results):
        if isinstance(result, Exception):
            if ctx.strict:
                raise result
            logger.warning(f"Modifier '{k}' failed: {result}")
            continue
        if result is None:
            continue
        sections = result if isinstance(result, list) else [result]
        for sec in sections:
            if not isinstance(sec, PromptSection):
                logger.warning(f"Modifier '{k}' returned non-section: {type(sec)} (ignored)")
                continue
            existing = collected.get(sec.id)
            collected[sec.id] = _merge(existing, sec)

    # stable order by weight then id
    return sorted(collected.values(), key=lambda s: (s.weight, s.id))


def _render(sections: List[PromptSection]) -> str:
    parts = [s.as_text() for s in sections if s.as_text()]
    return "\n\n".join(parts)


async def build_prompt(ctx: PromptContext, recipe: Optional[Iterable[str]] = None) -> str:
    """
    v2 async entry: plan -> execute (concurrent) -> render.
    """
    ordered, metas = _plan(ctx, recipe)
    sections = await _execute_all(ordered, metas, ctx)
    return _render(sections)


def build_prompt_sync(ctx: PromptContext, recipe: Optional[Iterable[str]] = None) -> str:
    """
    v2 sync entry: wraps build_prompt.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError("build_prompt_sync() cannot run inside an active event loop.")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(build_prompt(ctx, recipe))
