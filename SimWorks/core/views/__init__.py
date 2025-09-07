# core/views/__init__.py
from .views import *
from .failure_views import *

__all__ = []
__all__ += views.__all__
__all__ += failure_views.__all__