from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden


def is_inviter(user):
    return user.is_staff or user.is_superuser


def staff_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Staff access required.")
        return view_func(request, *args, **kwargs)

    return _wrapped
