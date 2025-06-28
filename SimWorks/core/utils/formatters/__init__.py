# core/utils/formatters/__init__.py
from . import builtins
from .base import Formatter
from .registry import registry

__all__ = ["Formatter", "describe_all_formats", "get_formatter_registry"]


def get_formatter_registry():
    return dict(registry.registry)


def describe_all_formats():
    return registry.describe()
