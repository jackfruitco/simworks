# simcore/ai/mixins/ident_namespace.py
"""Base mixin for chatlab OrchestrAI components."""

from orchestrai_django.identity import DjangoIdentityMixin

class ChatlabMixin(DjangoIdentityMixin):
    """Identity mixin for the chatlab app namespace."""
    namespace = "chatlab"
