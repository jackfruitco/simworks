# orchestrai_django/identity/utils.py


from django.apps import apps

# Populated at runtime by `orchestrai_django.apps.OrchestrAIDjangoConfig.ready()`
APP_IDENTITY_STRIP_TOKENS: tuple[str, ...] = ()

def infer_namespace_from_module(module_name: str) -> str:
    """Best-effort inference of a Django app label from a module name.

    Returns the matching Django AppConfig.label (lowercased) when the module
    sits inside a registered app; otherwise returns the first module segment
    lowercased.

    This is **not** identity derivation — it’s only a convenience for cases
    where callers need a lightweight namespace hint and do not have a class.
    """
    for app in apps.get_app_configs():
        if module_name.startswith(app.name):
            return app.label.lower()
    return module_name.split(".")[0].lower()


def get_app_identity_strip_tokens() -> tuple[str, ...]:
    """
    Return the app-contributed identity strip tokens as a tuple of strings.

    The return type is stable (always a tuple); callers should not mutate it.
    """
    # Ensure we always return a tuple even if someone set it to None or other
    value = APP_IDENTITY_STRIP_TOKENS or ()
    return tuple(value)
