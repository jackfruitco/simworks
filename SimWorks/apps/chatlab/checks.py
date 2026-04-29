# chatlab/checks.py

from collections import defaultdict

from django.core.checks import Error, Warning, register


@register()
def check_chatlab_modifier_catalog(app_configs, **kwargs):
    errors = []

    try:
        from apps.simcore.modifiers.loader import _clear_cache, load_lab_modifier_catalog

        _clear_cache()
        catalog = load_lab_modifier_catalog("chatlab")
    except Exception as exc:
        errors.append(
            Error(
                f"ChatLab modifier catalog failed to load: {exc}",
                hint="Ensure apps/chatlab/modifiers.yaml exists and is valid.",
                id="chatlab.E001",
            )
        )
        return errors

    group_keys = [g.key for g in catalog.groups]
    if len(group_keys) != len(set(group_keys)):
        errors.append(
            Error(
                "ChatLab modifier catalog has duplicate group keys.",
                hint=f"Group keys found: {group_keys!r}",
                id="chatlab.E002",
            )
        )

    for group in catalog.groups:
        mod_keys = [m.key for m in group.modifiers]
        if len(mod_keys) != len(set(mod_keys)):
            errors.append(
                Error(
                    f"Modifier group {group.key!r} has duplicate modifier keys.",
                    hint=f"Modifier keys found: {mod_keys!r}",
                    id="chatlab.E003",
                )
            )

    modifier_key_groups = defaultdict(list)
    for group in catalog.groups:
        for modifier in group.modifiers:
            modifier_key_groups[modifier.key].append(group.key)

    for modifier_key, group_keys in modifier_key_groups.items():
        if len(group_keys) > 1:
            errors.append(
                Error(
                    f"ChatLab modifier catalog has duplicate modifier key {modifier_key!r} across groups.",
                    hint=(
                        f"Modifier key {modifier_key!r} appears in groups: {group_keys!r}. "
                        "Modifier keys must be globally unique within a lab catalog."
                    ),
                    id="chatlab.E004",
                )
            )

    # Tolerant DB check — warn if catalog not seeded, but don't block startup
    try:
        from apps.simcore.models import ModifierCatalog

        if not ModifierCatalog.objects.filter(lab_type="chatlab", is_active=True).exists():
            errors.append(
                Warning(
                    "ChatLab modifier catalog is not seeded in the database.",
                    hint="Run: python manage.py sync_lab_modifiers --lab chatlab",
                    id="chatlab.W001",
                )
            )
    except Exception:
        pass  # DB not available yet (pre-migration), skip silently

    return errors
