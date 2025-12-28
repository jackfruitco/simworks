"""Compatibility shim for service runner protocol."""

from orchestrai.components.services.runners.base import BaseServiceRunner, TaskStatus

__all__ = ["BaseServiceRunner", "TaskStatus"]
