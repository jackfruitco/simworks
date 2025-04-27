# simcore/tools/base.py

from simcore.tools.registry import register_tool

class BaseTool:
    """
    Abstract Base Class for all simulation tools.
    """

    tool_name = None
    display_name = None
    is_generic = False

    def __init__(self, simulation):
        self.simulation = simulation
        if self.display_name is None and self.tool_name:
            self.display_name = self.tool_name.replace('_', ' ').title()

    @classmethod
    def register(cls):
        """Register the tool automatically."""
        if cls.tool_name is None:
            raise ValueError(f"{cls.__name__} must define a tool_name")

        @register_tool(cls.tool_name)
        def fetch_wrapper():
            def fetch(simulation):
                return cls(simulation).to_dict()
            return fetch

        return fetch_wrapper()

    def get_data(self):
        """Subclasses override this to provide data."""
        raise NotImplementedError

    def to_dict(self):
        """Subclasses must implement this to return a dictionary."""
        raise NotImplementedError

    def default_dict(self, data=None):
        return {
            "name": self.tool_name,
            "display_name": self.display_name,
            "data": data or [],
            "is_generic": self.is_generic,
        }

class GenericTool(BaseTool):
    """
    Generic simple metadata tool (k:v pairs).
    """
    is_generic = True

    def __init__(self, simulation):
        super().__init__(simulation)
        self.data = self.get_data()

    def get_data(self):
        """Return raw data (queryset, iterable) to be formatted into k:v."""
        raise NotImplementedError

    def to_dict(self):
        """Convert data into standard dictionary form."""
        if not hasattr(self.data, "__iter__"):
            raise ValueError(f"Data for {self.tool_name} must be iterable.")

        formatted_data = [{"key": m.key, "value": m.value} for m in self.data]
        return self.default_dict(data=formatted_data)