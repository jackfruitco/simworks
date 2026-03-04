"""Minimal BaseCodec compatibility shim."""

from __future__ import annotations

from typing import Any, ClassVar


class BaseCodec:
    """Legacy compatibility base for codecs.

    The modern service path no longer requires codecs, but some legacy imports
    still reference this base class and its small API surface.
    """

    abstract: ClassVar[bool] = True
    priority: ClassVar[int] = 0

    @classmethod
    def matches(cls, **_constraints: Any) -> bool:
        return True

    async def adecode(self, payload: Any) -> Any:
        return payload

    def decode(self, payload: Any) -> Any:
        return payload
