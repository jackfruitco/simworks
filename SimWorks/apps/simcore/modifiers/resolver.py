from __future__ import annotations

from .loader import load_lab_modifier_catalog
from .schemas import ModifierDefinition, ResolvedModifier


class UnknownModifierError(ValueError):
    pass


class SelectionConstraintError(ValueError):
    pass


def get_modifier_groups(lab_type: str) -> list[dict]:
    catalog = load_lab_modifier_catalog(lab_type)
    return [
        {
            "key": g.key,
            "label": g.label,
            "description": g.description,
            "selection": g.selection.model_dump(),
            "modifiers": [m.model_dump() for m in g.modifiers],
        }
        for g in catalog.groups
    ]


def get_modifier(lab_type: str, key: str) -> ModifierDefinition | None:
    catalog = load_lab_modifier_catalog(lab_type)
    for group in catalog.groups:
        for mod in group.modifiers:
            if mod.key == key:
                return mod
    return None


def resolve_modifiers(lab_type: str, keys: list[str]) -> list[ResolvedModifier]:
    catalog = load_lab_modifier_catalog(lab_type)
    lookup: dict[str, tuple] = {
        mod.key: (group, mod)
        for group in catalog.groups
        for mod in group.modifiers
    }

    unknown = [k for k in keys if k not in lookup]
    if unknown:
        raise UnknownModifierError(f"Unknown modifier keys: {unknown!r}")

    resolved: list[ResolvedModifier] = []
    group_selections: dict[str, list[str]] = {}

    for key in keys:
        group, mod = lookup[key]
        group_selections.setdefault(group.key, []).append(key)
        resolved.append(ResolvedModifier(key=key, group_key=group.key, definition=mod))

    for group in catalog.groups:
        if group.selection.mode == "single":
            selected = group_selections.get(group.key, [])
            if len(selected) > 1:
                raise SelectionConstraintError(
                    f"Group {group.key!r} is single-select but got keys: {selected!r}"
                )
        if group.selection.required and group.key not in group_selections:
            raise SelectionConstraintError(
                f"Group {group.key!r} is required but no modifier was selected."
            )

    return resolved


def render_modifier_prompt(lab_type: str, keys: list[str]) -> str:
    if not keys:
        return ""
    resolved = resolve_modifiers(lab_type, keys)
    return " ".join(
        r.definition.prompt_fragment
        for r in resolved
        if r.definition.prompt_fragment
    )
