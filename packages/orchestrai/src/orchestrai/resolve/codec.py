"""Codec resolver with precedence and priority-aware tie-breaking."""

from __future__ import annotations

import logging
from typing import Iterable

from orchestrai.components.codecs import BaseCodec

from .result import ResolutionBranch, ResolutionResult

logger = logging.getLogger(__name__)


def _codec_identity_label(codec_cls: type[BaseCodec]) -> str | None:
    ident = getattr(codec_cls, "identity", None)
    return getattr(ident, "as_str", None) or getattr(ident, "label", None)


def _unique(seq: Iterable) -> list:
    out = []
    for item in seq:
        if item not in out:
            out.append(item)
    return out


def _matches_constraints(codec_cls: type[BaseCodec], constraints: dict[str, object]) -> bool:
    if not constraints:
        return True
    matches = getattr(codec_cls, "matches", None)
    if not callable(matches):
        return False
    try:
        return bool(matches(**constraints))
    except Exception:
        logger.debug("codec constraint check failed for %s", codec_cls, exc_info=True)
        return False


def _sort_candidates(candidates: list[type[BaseCodec]]) -> list[type[BaseCodec]]:
    def _priority(cls: type[BaseCodec]) -> tuple[int, str]:
        prio = getattr(cls, "priority", 0)
        label = _codec_identity_label(cls) or getattr(cls, "__name__", "")
        return int(prio), label

    return sorted(candidates, key=_priority, reverse=True)


def resolve_codec(
        *,
        service,
        override: type[BaseCodec] | None = None,
        explicit: type[BaseCodec] | None = None,
        configured: Iterable[type[BaseCodec]] | None = None,
        constraints: dict[str, object] | None = None,
        store=None,
) -> ResolutionResult[type[BaseCodec] | None]:
    """Resolve a codec class for a service call."""

    if store is None:
        store = getattr(service, "component_store", None)
    if store is None:
        from orchestrai.registry.active_app import get_component_store as _get_component_store

        store = _get_component_store()
    branches: list[ResolutionBranch[type[BaseCodec] | None]] = []

    if override is not None:
        branch = ResolutionBranch(
            "override",
            override,
            identity=_codec_identity_label(override),
            reason="per-call codec override",
        )
        return ResolutionResult(override, branch, branches + [branch])

    if explicit is not None:
        branch = ResolutionBranch(
            "explicit",
            explicit,
            identity=_codec_identity_label(explicit),
            reason="codec_cls provided",
        )
        return ResolutionResult(explicit, branch, branches + [branch])

    candidates: list[type[BaseCodec]] = []

    for cand in configured or ():
        if cand not in candidates:
            candidates.append(cand)

    registry_candidates: list[type[BaseCodec]] = []
    if store is not None and constraints:
        try:
            registry = store.registry("codec")
            for cand in registry.items():
                if _matches_constraints(cand, constraints):
                    registry_candidates.append(cand)
        except Exception:
            logger.debug("codec resolution: registry lookup failed", exc_info=True)

    candidates.extend(x for x in registry_candidates if x not in candidates)

    if candidates:
        selected = _sort_candidates(candidates)[0]
        branch = ResolutionBranch(
            "candidates",
            selected,
            identity=_codec_identity_label(selected),
            reason="selected best matching codec",
            meta={
                "candidates": tuple(_codec_identity_label(c) or str(c) for c in candidates),
                "candidate_classes": tuple(candidates),
            },
        )
        return ResolutionResult(selected, branch, _unique(branches + [branch]))

    branch = ResolutionBranch("none", None, reason="no codec resolved")
    return ResolutionResult(None, branch, branches + [branch])


__all__ = ["resolve_codec"]
