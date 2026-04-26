# chatlab/checks.py

from django.core.checks import Error, register


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

    return errors
