"""Registration records used by the component store.

The new registry flow routes decorator registrations through an app-aware
component store. To keep registration deterministic and auditable, decorators
emit :class:`RegistrationRecord` instances that capture the component and its
resolved identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestrai.identity import Identity


@dataclass(frozen=True, slots=True)
class RegistrationRecord:
    """Immutable registration payload."""

    component: type[Any]
    identity: Identity
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.identity.kind

    @property
    def label(self) -> str:
        return self.identity.as_str


__all__ = ["RegistrationRecord"]
