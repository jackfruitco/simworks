# simcore/ai/codecs/feedback.py
from __future__ import annotations

from simcore_ai_django.api.decorators import ai_codec
from ..mixins import SimcoreMixin, FeedbackMixin


@ai_codec
class HotwashInitialCodec(SimcoreMixin, FeedbackMixin):
    """Codec for the initial patient feedback."""


