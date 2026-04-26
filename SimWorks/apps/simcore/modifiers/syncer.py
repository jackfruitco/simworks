from __future__ import annotations

from .loader import load_lab_modifier_catalog


def sync_lab_modifiers(lab_type: str, *, force: bool = False, dry_run: bool = False) -> dict:
    """Sync YAML modifier definitions into the DB for the given lab.

    Respects ``manually_edited`` on ModifierDefinition rows unless ``force=True``.
    Marks rows absent from YAML as inactive (never deletes).
    Returns a summary dict with created/updated/deactivated/skipped counts.
    """
    from apps.simcore.models import (
        ModifierCatalog,
        ModifierDefinition,
        ModifierGroup,
    )

    catalog_schema = load_lab_modifier_catalog(lab_type)

    summary: dict = {
        "catalog": None,
        "groups_created": 0,
        "groups_updated": 0,
        "groups_deactivated": 0,
        "defs_created": 0,
        "defs_updated": 0,
        "defs_deactivated": 0,
        "defs_skipped": 0,
    }

    if dry_run:
        # Compute what would change without writing anything.
        try:
            catalog_obj = ModifierCatalog.objects.get(lab_type=lab_type)
        except ModifierCatalog.DoesNotExist:
            summary["catalog"] = "create"
            summary["groups_created"] = len(catalog_schema.groups)
            summary["defs_created"] = sum(len(g.modifiers) for g in catalog_schema.groups)
            return summary

        summary["catalog"] = "existing"
        yaml_group_keys = {g.key for g in catalog_schema.groups}

        for idx, group_schema in enumerate(catalog_schema.groups):
            try:
                group_obj = ModifierGroup.objects.get(catalog=catalog_obj, key=group_schema.key)
                # Check if update needed
                fields_changed = any(
                    [
                        group_obj.label != group_schema.label,
                        group_obj.description != group_schema.description,
                        group_obj.selection_mode != group_schema.selection.mode,
                        group_obj.required != group_schema.selection.required,
                        group_obj.sort_order != idx,
                        not group_obj.is_active,
                    ]
                )
                if fields_changed:
                    summary["groups_updated"] += 1

                yaml_mod_keys = {m.key for m in group_schema.modifiers}
                for midx, mod_schema in enumerate(group_schema.modifiers):
                    try:
                        mod_obj = ModifierDefinition.objects.get(
                            group=group_obj, key=mod_schema.key
                        )
                        if mod_obj.manually_edited and not force:
                            summary["defs_skipped"] += 1
                            continue
                        fields_changed = any(
                            [
                                mod_obj.label != mod_schema.label,
                                mod_obj.description != mod_schema.description,
                                mod_obj.prompt_fragment != (mod_schema.prompt_fragment or ""),
                                mod_obj.sort_order != midx,
                                not mod_obj.is_active,
                            ]
                        )
                        if fields_changed:
                            summary["defs_updated"] += 1
                    except ModifierDefinition.DoesNotExist:
                        summary["defs_created"] += 1

                summary["defs_deactivated"] += (
                    ModifierDefinition.objects.filter(group=group_obj, is_active=True)
                    .exclude(key__in=yaml_mod_keys)
                    .count()
                )

            except ModifierGroup.DoesNotExist:
                summary["groups_created"] += 1
                summary["defs_created"] += len(group_schema.modifiers)

        summary["groups_deactivated"] += (
            ModifierGroup.objects.filter(catalog=catalog_obj, is_active=True)
            .exclude(key__in=yaml_group_keys)
            .count()
        )

        return summary

    # --- Live write path ---

    catalog_obj, cat_created = ModifierCatalog.objects.update_or_create(
        lab_type=lab_type,
        defaults={
            "version": catalog_schema.version,
            "is_active": True,
            "source": "yaml",
        },
    )
    summary["catalog"] = "created" if cat_created else "updated"

    yaml_group_keys = {g.key for g in catalog_schema.groups}

    for idx, group_schema in enumerate(catalog_schema.groups):
        group_obj, g_created = ModifierGroup.objects.get_or_create(
            catalog=catalog_obj,
            key=group_schema.key,
            defaults={
                "label": group_schema.label,
                "description": group_schema.description,
                "selection_mode": group_schema.selection.mode,
                "required": group_schema.selection.required,
                "sort_order": idx,
                "is_active": True,
            },
        )
        if g_created:
            summary["groups_created"] += 1
        else:
            updated_fields = []
            for field, val in [
                ("label", group_schema.label),
                ("description", group_schema.description),
                ("selection_mode", group_schema.selection.mode),
                ("required", group_schema.selection.required),
                ("sort_order", idx),
                ("is_active", True),
            ]:
                if getattr(group_obj, field) != val:
                    setattr(group_obj, field, val)
                    updated_fields.append(field)
            if updated_fields:
                group_obj.save(update_fields=updated_fields)
                summary["groups_updated"] += 1

        yaml_mod_keys = {m.key for m in group_schema.modifiers}

        for midx, mod_schema in enumerate(group_schema.modifiers):
            mod_obj, m_created = ModifierDefinition.objects.get_or_create(
                group=group_obj,
                key=mod_schema.key,
                defaults={
                    "label": mod_schema.label,
                    "description": mod_schema.description,
                    "prompt_fragment": mod_schema.prompt_fragment or "",
                    "sort_order": midx,
                    "is_active": True,
                    "manually_edited": False,
                },
            )
            if m_created:
                summary["defs_created"] += 1
            else:
                if mod_obj.manually_edited and not force:
                    summary["defs_skipped"] += 1
                    continue
                updated_fields = []
                for field, val in [
                    ("label", mod_schema.label),
                    ("description", mod_schema.description),
                    ("prompt_fragment", mod_schema.prompt_fragment or ""),
                    ("sort_order", midx),
                    ("is_active", True),
                ]:
                    if getattr(mod_obj, field) != val:
                        setattr(mod_obj, field, val)
                        updated_fields.append(field)
                if updated_fields:
                    mod_obj.save(update_fields=updated_fields)
                    summary["defs_updated"] += 1

        # Deactivate modifiers removed from YAML (never delete)
        deactivated = (
            ModifierDefinition.objects.filter(group=group_obj, is_active=True)
            .exclude(key__in=yaml_mod_keys)
            .update(is_active=False)
        )
        summary["defs_deactivated"] += deactivated

    # Deactivate groups removed from YAML (never delete)
    deactivated_groups = (
        ModifierGroup.objects.filter(catalog=catalog_obj, is_active=True)
        .exclude(key__in=yaml_group_keys)
        .update(is_active=False)
    )
    summary["groups_deactivated"] += deactivated_groups

    return summary
