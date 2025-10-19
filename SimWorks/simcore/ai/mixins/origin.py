# simcore/ai/mixins/origin.py
from __future__ import annotations

from simcore_ai_django.api.mixins import DjangoIdentityMixin


class SimcoreMixin(DjangoIdentityMixin):
    """Identity mixin for the simcore app origin."""
    origin = "simcore"
