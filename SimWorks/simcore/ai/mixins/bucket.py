# simcore/ai/mixins/bucket.py
from __future__ import annotations

from simcore_ai_django.api.mixins import IdentityMixin


class StandardizedPatientMixin(IdentityMixin):
    """Identity mixin for the standardized patient bucket."""
    bucket = "standardized_patient"


class FeedbackMixin(IdentityMixin):
    """Identity mixin for the feedback bucket."""
    bucket = "feedback"
