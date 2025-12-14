# simcore/ai/mixins/ident_namespace.py
"""Base mixin for chatlab prompt sections."""

from orchestrai_django.api.mixins import DjangoIdentityMixin

class ChatlabMixin(DjangoIdentityMixin):
    """Identity mixin for the chatlab app namespace."""
    namespace = "chatlab"
