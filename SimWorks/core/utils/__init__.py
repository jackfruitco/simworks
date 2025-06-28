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

from .accounts import get_or_create_system_user
from .accounts import get_system_user
from .formatters import Formatter
from .hash import compute_fingerprint
from .logging import AppColorFormatter
from .logging import log_model_save
from .system import check_env
from .system import coerce_to_bool
from .system import remove_null_keys
