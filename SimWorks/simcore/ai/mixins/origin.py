# simcore/ai/mixins/origin.py
from __future__ import annotations

from simcore_ai.types.identity import IdentityMixin


class SimcoreMixin(IdentityMixin):
    """Identity mixin for the simcore app origin."""
    origin = "simcore"
