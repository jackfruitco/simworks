class FormatterRegistry:
    def __init__(self):
        self.registry = {}
        self._extension_map = {
            "json": "json",
            "csv": "csv",
            "md": "markdown",
            "markdown": "markdown",
        }

    @property
    def extension_map(self):
        """
        Expose the extension map for safe external access.
        """
        return dict(self._extension_map)

    def register(self, name: str, extension: str = None):
        """
        Decorator to register a formatter function under a given format name.
        Optionally maps a file extension to that format.
        """

        def decorator(func):
            self.registry[name.lower()] = func
            if extension:
                self._extension_map[extension.lower()] = name.lower()
            return func

        return decorator

    def get(self, name: str):
        """
        Retrieve a formatter by format name.
        """
        return self.registry.get(name.lower())

    def get_by_extension(self, extension: str):
        """
        Look up a formatter by file extension (e.g., 'md' → 'markdown' → formatter function).
        """
        format_name = self.extension_map.get(extension.lower())
        return self.get(format_name) if format_name else None

    def get_with_fallback(self, name: str, fallback: str = "json"):
        """
        Retrieve a formatter by name, falling back to a default if not found.
        """
        result = self.get(name)
        if result:
            return result
        result = self.get(fallback)
        if result:
            return result
        raise ValueError(f"No formatter found for '{name}' or fallback '{fallback}'")

    def available_formats(self):
        """
        List all registered formatter names.
        """
        return list(self.registry.keys())

    def describe(self):
        """
        Return a dictionary with detailed info on formatters and extensions:
        - formats: mapping of name → docstring
        - extensions: mapping of extension → format
        """
        return {
            "formats": {
                name: func.__doc__.strip() if func.__doc__ else "No description."
                for name, func in self.registry.items()
            },
            "extensions": dict(self.extension_map),
        }


registry = FormatterRegistry()
register_formatter = registry.register