# simcore/tools/registry.py

_registry = {}

def register_tool(cls):
    """Decorator to register a Tool class and add a classmethod 'fetch'."""
    if not hasattr(cls, "tool_name"):
        raise ValueError(f"{cls.__name__} must define 'tool_name' attribute.")

    @classmethod
    def fetch(cls, simulation):
        return cls(simulation).to_dict()

    cls.fetch = fetch

    _registry[cls.tool_name.lower()] = cls
    return cls

def get_tool(name):
    """Fetch a tool class by name (case insensitive)."""
    tool_class = _registry.get(name.lower())
    return tool_class

def list_tools():
    """List all registered tool names."""
    return list(_registry.values())