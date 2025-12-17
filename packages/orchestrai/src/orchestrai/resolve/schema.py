"""Response schema resolver with adapter application."""

from __future__ import annotations

import logging
from typing import Iterable

from orchestrai.components.schemas import BaseOutputSchema, sort_adapters
from orchestrai.identity import Identity

from .result import ResolutionBranch, ResolutionResult

logger = logging.getLogger(__name__)


def apply_schema_adapters(
        schema_cls: type[BaseOutputSchema] | None,
        adapters: Iterable,
) -> dict | None:
    """Return an adapted JSON schema when a model and adapters exist."""

    if schema_cls is None:
        return None

    try:
        schema_json = schema_cls.model_json_schema()
    except Exception:
        logger.debug("schema resolution: model_json_schema failed", exc_info=True)
        return None

    out = schema_json
    for adapter in sort_adapters(adapters or ()):  # type: ignore[arg-type]
        try:
            out = adapter.adapt(out)
        except Exception:  # pragma: no cover - adapter bugs should surface clearly
            logger.debug("schema adapter %r failed", adapter, exc_info=True)
            raise
    return out


def resolve_schema(
        *,
        identity,
        override: type[BaseOutputSchema] | None = None,
        default: type[BaseOutputSchema] | None = None,
        adapters: Iterable | None = None,
        store=None,
) -> ResolutionResult[type[BaseOutputSchema] | None]:
    """Resolve a response schema with simple precedence."""

    if store is None:
        from orchestrai.registry.active_app import get_component_store as _get_component_store

        store = _get_component_store()
    branches: list[ResolutionBranch[type[BaseOutputSchema] | None]] = []

    if override is not None:
        branch = ResolutionBranch(
            "override",
            override,
            identity=getattr(override, "identity", None).as_str if hasattr(override, "identity") else None,
            reason="response_schema override provided",
        )
        branch.meta["schema_json"] = apply_schema_adapters(override, adapters or ())
        return ResolutionResult(override, branch, branches + [branch])

    if default is not None:
        branch = ResolutionBranch(
            "class",
            default,
            identity=getattr(default, "identity", None).as_str if hasattr(default, "identity") else None,
            reason="class-level response_schema",
        )
        branch.meta["schema_json"] = apply_schema_adapters(default, adapters or ())
        return ResolutionResult(default, branch, branches + [branch])

    candidate = None
    if store is not None:
        lookup_ident = identity
        if isinstance(identity, Identity):
            lookup_ident = Identity(
                domain=identity.domain,
                namespace=identity.namespace,
                group="schema",
                name=identity.name,
            )
        try:
            candidate = store.try_get("schema", lookup_ident)
        except Exception:
            logger.debug("schema resolution: ComponentStore lookup failed", exc_info=True)

    if candidate is not None:
        branch = ResolutionBranch(
            "registry",
            candidate,
            identity=getattr(candidate, "identity", None).as_str if hasattr(candidate, "identity") else None,
            reason="matched schema in ComponentStore",
        )
        branch.meta["schema_json"] = apply_schema_adapters(candidate, adapters or ())
        return ResolutionResult(candidate, branch, branches + [branch])

    branch = ResolutionBranch("none", None, reason="no response schema resolved")
    return ResolutionResult(None, branch, branches + [branch])


__all__ = [
    "apply_schema_adapters",
    "resolve_schema",
]
