# core/decorators.py

from functools import wraps
from asgiref.sync import sync_to_async
from django.utils.functional import SimpleLazyObject

def resolve_user(view_func):
    @wraps(view_func)
    async def _wrapped_view(request, *args, **kwargs):
        if isinstance(request.user, SimpleLazyObject):
            request.user = await request.auser()
        return await view_func(request, *args, **kwargs)
    return _wrapped_view