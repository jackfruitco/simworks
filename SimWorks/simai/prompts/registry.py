# SimWorks/simai/prompts/registry.py

_registry = {}

def register_modifier(label):
    """Decorator to register a prompt modifier function under a label."""
    def decorator(func):
        if label.lower() in _registry:
            raise ValueError(f"Modifier '{label}' is already registered.")
        _registry[label.lower()] = func
        return func
    return decorator

def get_modifier(label):
    return _registry.get(label.lower())

def list_modifiers():
    """Returns a list of (label, function) tuples."""
    return list(_registry.items())

# Alias for external use
PromptModifiers = {
    "register": register_modifier,
    "get": get_modifier,
    "list": list_modifiers,
}