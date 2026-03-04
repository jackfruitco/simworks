# orchestrai/decorators/__init__.py
"""Decorator facade (lazy imports to avoid cycles).

This package exposes the base registration decorator and *optionally* the
domain-specific decorator classes/instances via **lazy** attribute access.
We avoid importing domain modules (services, codecs, instructions, schemas)
at import time to prevent circular imports during early Django startup.
"""


from .base import BaseDecorator
from .components import *


class _OrcaDecorators:
    """Namespace providing convenient access to all OrchestrAI decorators.

    Usage::

        from orchestrai.decorators import orca

        @orca.instruction(order=10)
        class MyInstruction(BaseInstruction): ...

        @orca.service
        class MyService(BaseService): ...
    """

    @property
    def service(self):
        from .components import service
        return service

    @property
    def codec(self):
        from .components import codec
        return codec

    @property
    def schema(self):
        from .components import schema
        return schema

    @property
    def instruction(self):
        from .components import instruction
        return instruction


orca = _OrcaDecorators()


__all__ = [
    "BaseDecorator",
    "codec",
    "service",
    "schema",
    "instruction",
    "orca",
]
