# core/decorators.py
from functools import wraps

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.utils.functional import SimpleLazyObject

User = get_user_model()


def resolve_user(view_func):
    @wraps(view_func)
    async def _wrapped_view(request, *args, **kwargs):
        if isinstance(request.user, SimpleLazyObject):
            request.user = await request.auser()

        if isinstance(request.user, AnonymousUser):
            return await view_func(request, *args, **kwargs)

        # Replace user with a version that has .role prefetched
        user_id = request.user.pk
        request.user = await sync_to_async(
            lambda: User.objects.select_related("role").get(pk=user_id)
        )()

        return await view_func(request, *args, **kwargs)

    return _wrapped_view
