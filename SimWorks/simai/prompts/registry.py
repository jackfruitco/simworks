# SimWorks/simai/prompts/registry.py
import logging

logger = logging.getLogger(__name__)
_registry = {}

def register_modifier(k):
    """Decorator to register a prompt modifier function under a key."""
    def decorator(func):
        key = k.casefold()
        if key in _registry:
            raise ValueError(f"Modifier '{k}' is already registered.")
        parts = k.split(".")
        group = parts[0] if len(parts) > 1 else "default"
        name = parts[1] if len(parts) > 1 else parts[0]
        _registry[key] = {
            "key": k,
            "group": group,
            "name": name,
            "value": func,
            "description": func.__doc__ or "",
        }
        logger.debug(f"Modifier registered: '{k}'")
        return func
    return decorator

def get_modifier(k):
    logger.debug(f"Looking up modifier: '{k}'")
    k = k.casefold()
    if k in _registry:
        return _registry[k]
    # Attempt backward traversal by dot path (lab.chatlab.default → lab.chatlab → lab)
    parts = k.split(".")
    for i in reversed(range(1, len(parts))):
        attempt = ".".join(parts[:i])
        logger.debug(f"Attempting fallback lookup: '{attempt}'")
        if attempt in _registry:
            return _registry[attempt]
    logger.debug(f"No modifier found for key: '{k}'")
    return None

def list_modifiers():
    """Returns a list of modifier metadata dicts."""
    return list(_registry.values())

# Alias for external use
class PromptModifiers:
    register = staticmethod(register_modifier)
    get = staticmethod(get_modifier)
    list = staticmethod(list_modifiers)