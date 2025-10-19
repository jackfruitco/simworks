# simcore_ai/identity/__init__.py

from .base import Identity
from .mixins import IdentityMixin
from .utils import *

__all__ = [
    "Identity",
    "IdentityMixin",
    "DEFAULT_STRIP_TOKENS",
    "snake",
    "strip_tokens",
    "derive_name_from_class",
    "module_root",
    "derive_identity_for_class",
    "resolve_collision",
    "parse_dot_identity",
]


