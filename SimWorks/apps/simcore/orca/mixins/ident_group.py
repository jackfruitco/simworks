# simcore/ai/mixins/ident_group.py


from orchestrai_django.identity import DjangoIdentityMixin


class StandardizedPatientMixin(DjangoIdentityMixin):
    """Identity mixin for the standardized patient group."""
    group = "standardized_patient"


class FeedbackMixin(DjangoIdentityMixin):
    """Identity mixin for the feedback group."""
    group = "feedback"
