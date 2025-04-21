# core/utils/formatters/__init__.py
from .base import Formatter
from .registry import registry
from .base import Formatter
from .registry import registry
from . import builtins

__all__ = ["Formatter", "describe_all_formats", "get_formatter_registry"]


def get_formatter_registry():
    return dict(registry.registry)

def describe_all_formats():
    return registry.describe()
