# simcore/ai/mixins/ident_namespace.py


from orchestrai_django.api.mixins import DjangoIdentityMixin


class SimcoreMixin(DjangoIdentityMixin):
    """Identity mixin for the simcore app namespace."""
    namespace = "simcore"
