# simcore/ai/mixins/ident_kind.py


from orchestrai_django.identity import DjangoIdentityMixin


class StandardizedPatientMixin(DjangoIdentityMixin):
    """Identity mixin for the standardized patient kind."""
    kind = "standardized_patient"


class FeedbackMixin(DjangoIdentityMixin):
    """Identity mixin for the feedback kind."""
    kind = "feedback"
