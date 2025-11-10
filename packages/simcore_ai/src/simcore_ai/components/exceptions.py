from __future__ import annotations

from simcore_ai.exceptions import SimCoreError


class ComponentError(SimCoreError):
    pass


class ComponentNotFoundError(ComponentError, AttributeError):
    pass
