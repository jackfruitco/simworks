"""
core.utils

This module exposes a curated set of utility functions and classes used across the SimWorks project.
Each utility is grouped by domain (e.g., accounts, logging, formatters) and implemented in its own module.
"""
from .accounts import get_or_create_system_user
from .accounts import get_system_user
from .formatters import Formatter
from .hash import compute_fingerprint
from .logging import AppColorFormatter
from .logging import log_model_save
from .string_utils import to_camel_case
from .string_utils import to_pascal_case
from .string_utils import to_snake_case
from .system import check_env
from .system import coerce_to_bool
from .system import remove_null_keys

__all__ = [
    "get_system_user",
    "get_or_create_system_user",
    "Formatter",
    "compute_fingerprint",
    "AppColorFormatter",
    "log_model_save",
    "to_snake_case",
    "to_camel_case",
    "to_pascal_case",
    "check_env",
    "coerce_to_bool",
    "remove_null_keys",
]