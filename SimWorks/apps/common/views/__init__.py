# common/views/__init__.py
from .failure_views import *
from .views import *

__all__ = []
__all__ += views.__all__
__all__ += failure_views.__all__
