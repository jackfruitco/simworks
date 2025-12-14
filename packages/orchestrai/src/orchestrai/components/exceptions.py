

from orchestrai.exceptions import SimCoreError


class ComponentError(SimCoreError):
    pass


class ComponentNotFoundError(ComponentError, AttributeError):
    pass
