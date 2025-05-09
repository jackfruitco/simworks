# SimWorks/simai/prompts/registry.py
import logging

logger = logging.getLogger(__name__)
_registry = {}

def register_modifier(label):
    """Decorator to register a prompt modifier function under a label."""
    def decorator(func):
        key = label.lower()
        if key in _registry:
            raise ValueError(f"Modifier '{label}' is already registered.")
        parts = label.split(".")
        group = parts[0] if len(parts) > 1 else "default"
        name = parts[1] if len(parts) > 1 else parts[0]
        _registry[key] = {
            "key": label,
            "group": group,
            "name": name,
            "value": func,
            "description": func.__doc__ or "",
        }
        logger.info(f"Modifier registered: '{label}'")
        return func
    return decorator

def get_modifier(label):
    return _registry.get(label.lower())

def list_modifiers():
    """Returns a list of modifier metadata dicts."""
    return list(_registry.values())

# Alias for external use
PromptModifiers = {
    "register": register_modifier,
    "get": get_modifier,
    "list": list_modifiers,
}