# simcore_ai_django/api/mixins.py
"""Contains mixins for simcore AI Django integration.

This module imports and makes available mixins that are essential for
identity management in simcore AI Django applications.

Exports:
    IdentityMixin (class): Identity handling mixin for simcore AI types.
"""


from simcore_ai_django.identity.mixins import DjangoIdentityMixin

__all__ = [
    "DjangoIdentityMixin",
]