# SimWorks/simai/prompts/registry.py

class ModifierRegistry:
    def __init__(self):
        self._modifiers = {}

    def register(self, label, func):
        key = label.lower()
        if key in self._modifiers:
            raise ValueError(f"Modifier '{label}' is already registered.")
        self._modifiers[key] = func

    def get(self, label):
        return self._modifiers.get(label.lower())

modifiers = ModifierRegistry()