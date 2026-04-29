from __future__ import annotations

from .schemas import ModifierDefinitionSchema, ResolvedModifier


class UnknownModifierError(ValueError):
    pass


class SelectionConstraintError(ValueError):
    pass


def _get_active_catalog(lab_type: str):
    from django.core.exceptions import ImproperlyConfigured

    from apps.simcore.models import ModifierCatalog

    try:
        return ModifierCatalog.objects.get(lab_type=lab_type, is_active=True)
    except ModifierCatalog.DoesNotExist as exc:
        raise ImproperlyConfigured(
            f"No active modifier catalog for lab_type={lab_type!r}. "
            f"Run: python manage.py sync_lab_modifiers --lab {lab_type}"
        ) from exc


def get_modifier_groups(lab_type: str) -> list[dict]:
    from apps.simcore.models import ModifierGroup

    catalog = _get_active_catalog(lab_type)
    groups = (
        ModifierGroup.objects.filter(catalog=catalog, is_active=True)
        .prefetch_related("modifiers")
        .order_by("sort_order", "key")
    )
    return [
        {
            "key": g.key,
            "label": g.label,
            "description": g.description,
            "selection": {"mode": g.selection_mode, "required": g.required},
            "modifiers": [
                {
                    "key": m.key,
                    "label": m.label,
                    "description": m.description,
                    "prompt_fragment": m.prompt_fragment or None,
                }
                for m in g.modifiers.filter(is_active=True).order_by("sort_order", "key")
            ],
        }
        for g in groups
    ]


def get_modifier(lab_type: str, key: str) -> ModifierDefinitionSchema | None:
    from apps.simcore.models import ModifierDefinition

    catalog = _get_active_catalog(lab_type)
    try:
        m = ModifierDefinition.objects.get(
            group__catalog=catalog,
            group__is_active=True,
            key=key,
            is_active=True,
        )
        return ModifierDefinitionSchema(
            key=m.key,
            label=m.label,
            description=m.description,
            prompt_fragment=m.prompt_fragment or None,
        )
    except ModifierDefinition.DoesNotExist:
        return None


def resolve_modifiers(lab_type: str, keys: list[str]) -> list[ResolvedModifier]:
    from apps.simcore.models import ModifierDefinition, ModifierGroup

    catalog = _get_active_catalog(lab_type)
    mods = (
        ModifierDefinition.objects.filter(
            group__catalog=catalog,
            group__is_active=True,
            is_active=True,
            key__in=keys,
        ).select_related("group")
        if keys
        else []
    )
    found_keys = {m.key: m for m in mods}

    unknown = [k for k in keys if k not in found_keys]
    if unknown:
        raise UnknownModifierError(f"Unknown modifier keys: {unknown!r}")

    resolved: list[ResolvedModifier] = []
    group_selections: dict[str, list[str]] = {}

    for key in keys:
        m = found_keys[key]
        group_selections.setdefault(m.group.key, []).append(key)
        resolved.append(
            ResolvedModifier(
                key=key,
                group_key=m.group.key,
                definition=ModifierDefinitionSchema(
                    key=m.key,
                    label=m.label,
                    description=m.description,
                    prompt_fragment=m.prompt_fragment or None,
                ),
            )
        )

    groups_qs = ModifierGroup.objects.filter(catalog=catalog, is_active=True)
    for group in groups_qs:
        selected = group_selections.get(group.key, [])
        if group.required and not selected:
            raise SelectionConstraintError(
                f"Group {group.key!r} is required but no modifier was selected."
            )
        if group.selection_mode == "single" and len(selected) > 1:
            raise SelectionConstraintError(
                f"Group {group.key!r} is single-select but got keys: {selected!r}"
            )

    return resolved


def render_modifier_prompt(lab_type: str, keys: list[str]) -> str:
    if not keys:
        return ""
    resolved = resolve_modifiers(lab_type, keys)
    return "\n".join(r.definition.prompt_fragment for r in resolved if r.definition.prompt_fragment)


def render_modifier_prompt_from_snapshot(snapshot: list[dict]) -> str:
    """Render prompt from a pre-built modifier_snapshot list (no DB read)."""
    fragments = [
        entry.get("prompt_fragment", "") for entry in snapshot if entry.get("prompt_fragment")
    ]
    return "\n".join(fragments)
