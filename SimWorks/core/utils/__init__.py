"""
core.utils

This module exposes a curated set of utility functions and classes used across the SimWorks project.
Each utility is grouped by domain (e.g., accounts, logging, formatters) and implemented in its own module.

Import from here when you want top-level access to common helpers like:
    - get_system_user
    - compute_fingerprint
    - log_model_save
    - Formatter (for formatting scenario logs)
"""

from .accounts import get_system_user, get_or_create_system_user
from .system import check_env, coerce_to_bool, remove_null_keys
from .hash import compute_fingerprint
from .logging import log_model_save, AppColorFormatter
from .formatters import Formatter