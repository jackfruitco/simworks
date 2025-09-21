# SimWorks/simai/promptkit/builtin_v2.py
from __future__ import annotations

import asyncio
import inspect
from typing import Optional

from .modifiers import modifier
from .types import PromptContext, PromptSection

# Bridge to existing content where appropriate
from .registry import PromptModifiers  # existing v1 registry
from .base import DEFAULT_PROMPT_BASE  # reuse existing base content


def _call_maybe_async(func, *args, **kwargs) -> asyncio.Future:
    if inspect.iscoroutinefunction(func):
        return func(*args, **kwargs)
    # run sync callable in a thread via asyncio.to_thread for safety
    return asyncio.to_thread(func, *args, **kwargs)


@modifier(
    key="defaults.base",
    phase="defaults",
    default=True,
    priority=0,
    tags={"defaults"},
)
async def defaults_base(ctx: PromptContext) -> Optional[PromptSection]:
    if not DEFAULT_PROMPT_BASE:
        return None
    return PromptSection(
        id="defaults/base",
        content=DEFAULT_PROMPT_BASE.strip(),
        merge="first",
        tags={"defaults"},
    )


@modifier(
    key="persona.user",
    phase="persona",
    default=True,
    priority=10,
    tags={"persona"},
)
async def persona_user(ctx: PromptContext) -> Optional[PromptSection]:
    """
    Bridges to existing 'User.role' content if available.
    """
    entry = PromptModifiers.get("User.role")
    if not entry:
        return None
    func = entry.get("value")
    if not func:
        return None
    # v1 function signature: func(user, role) -> str (possibly sync)
    result = await _call_maybe_async(func, ctx.user, ctx.role)
    if not result:
        return None
    return PromptSection(
        id="persona/user",
        content=str(result).strip(),
        merge="last",
        tags={"persona"},
    )


@modifier(
    key="history.user",
    phase="history",
    default=True,
    priority=0,
    tags={"history"},
)
async def history_user(ctx: PromptContext) -> Optional[PromptSection]:
    """
    Bridges to existing 'User.history' if include_history is enabled and user present.
    """
    if not ctx.include_history or not ctx.user:
        return None
    entry = PromptModifiers.get("User.history")
    if not entry:
        return None
    func = entry.get("value")
    if not func:
        return None
    # heuristic: within_days may be specified in payload
    within_days = ctx.payload.get("history_within_days", 180)
    result = await _call_maybe_async(func, user=ctx.user, within_days=within_days)
    if not result:
        return None
    return PromptSection(
        id="history/user",
        content=str(result).strip(),
        merge="concat",
        tags={"history"},
    )


@modifier(
    key="lab.chatlab",
    phase="lab",
    default=False,
    priority=0,
    tags={"lab"},
)
async def lab_chatlab(ctx: PromptContext) -> Optional[PromptSection]:
    entry = PromptModifiers.get("Lab.ChatLab")
    if not entry:
        return None
    func = entry.get("value")
    if not func:
        return None
    result = await _call_maybe_async(func, user=ctx.user, role=ctx.role)
    if not result:
        return None
    return PromptSection(
        id="lab/chatlab",
        content=str(result).strip(),
        merge="concat",
        tags={"lab"},
    )


@modifier(
    key="lab.trainerlab",
    phase="lab",
    default=False,
    priority=0,
    tags={"lab"},
)
async def lab_trainerlab(ctx: PromptContext) -> Optional[PromptSection]:
    entry = PromptModifiers.get("Lab.TrainerLab")
    if not entry:
        return None
    func = entry.get("value")
    if not func:
        return None
    result = await _call_maybe_async(func, user=ctx.user, role=ctx.role)
    if not result:
        return None
    return PromptSection(
        id="lab/trainerlab",
        content=str(result).strip(),
        merge="concat",
        tags={"lab"},
    )
