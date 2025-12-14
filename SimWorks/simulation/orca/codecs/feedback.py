# simcore/ai/codecs/feedback.py


from orchestrai_django.decorators import codec
from ..mixins import SimcoreMixin, FeedbackMixin


@codec
class HotwashInitialCodec(SimcoreMixin, FeedbackMixin):
    """Codec for the initial patient feedback."""


