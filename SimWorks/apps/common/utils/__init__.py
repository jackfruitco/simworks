"""
common.utils

This module exposes a curated set of utility functions and classes used across the SimWorks project.
Each utility is grouped by domain (e.g., accounts, logging, formatters) and implemented in its own module.
"""

from .accounts import aget_or_create_system_user, get_or_create_system_user, get_system_user
from .formatters import Formatter
from .hash import compute_fingerprint
from .logging import AppColorFormatter, log_model_save
from .string_utils import to_camel_case, to_pascal_case, to_snake_case
from .system import check_env, coerce_to_bool, remove_null_keys

__all__ = [
    "AppColorFormatter",
    "Formatter",
    "check_env",
    "coerce_to_bool",
    "compute_fingerprint",
    "get_or_create_system_user",
    "get_system_user",
    "log_model_save",
    "remove_null_keys",
    "to_camel_case",
    "to_pascal_case",
    "to_snake_case",
]
