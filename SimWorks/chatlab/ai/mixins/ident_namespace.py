# simcore/ai/mixins/ident_namespace.py
"""Base mixin for chatlab prompt sections."""

from simcore_ai_django.api.mixins import DjangoIdentityMixin

class ChatlabMixin(DjangoIdentityMixin):
    """Identity mixin for the chatlab app namespace."""
    namespace = "chatlab"
