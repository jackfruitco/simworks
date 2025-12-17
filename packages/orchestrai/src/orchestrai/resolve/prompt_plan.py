"""Prompt plan resolver."""

from __future__ import annotations

import logging
from typing import Iterable

from orchestrai.components.promptkit import PromptPlan, PromptSection
from orchestrai.identity import Identity

from .result import ResolutionBranch, ResolutionResult

logger = logging.getLogger(__name__)


def _iter_unique(seq: Iterable) -> list:
    out = []
    for item in seq:
        if item not in out:
            out.append(item)
    return out


def resolve_prompt_plan(service) -> ResolutionResult[PromptPlan | None]:
    """Resolve the prompt plan for a service (explicit → registry → none)."""

    store = getattr(service, "component_store", None)
    if store is None:
        from orchestrai.registry.active_app import get_component_store as _get_component_store

        store = _get_component_store()
    branches: list[ResolutionBranch[PromptPlan | None]] = []

    # Explicit plan (ctor or class default, pre-normalized in the service)
    if getattr(service, "_prompt_plan", None) is not None:
        plan = service._prompt_plan
        branch = ResolutionBranch(
            "explicit",
            plan,
            reason=f"provided via {getattr(service, '_prompt_plan_source', 'explicit')}",
        )
        return ResolutionResult(plan, branch, _iter_unique(branches + [branch]))

    # Registry match: prompt section whose identity matches the service
    section_cls = None
    if store is not None:
        lookup_ident = getattr(service, "identity", None)
        if isinstance(lookup_ident, Identity):
            lookup_ident = Identity(
                domain=lookup_ident.domain,
                namespace=lookup_ident.namespace,
                group="prompt_section",
                name=lookup_ident.name,
            )
        try:
            section_cls = store.try_get("prompt_section", lookup_ident or service.identity)
        except Exception:  # pragma: no cover - defensive
            logger.debug("prompt plan resolution: prompt_section lookup failed", exc_info=True)

    if section_cls is not None:
        plan = PromptPlan.from_sections([section_cls])
        branch = ResolutionBranch(
            "registry",
            plan,
            identity=getattr(section_cls, "identity", None).as_str if hasattr(section_cls, "identity") else None,
            reason="matched prompt_section in ComponentStore",
        )
        return ResolutionResult(plan, branch, _iter_unique(branches + [branch]))

    branch = ResolutionBranch("none", None, reason="no prompt plan available")
    return ResolutionResult(None, branch, _iter_unique(branches + [branch]))


__all__ = ["resolve_prompt_plan"]
