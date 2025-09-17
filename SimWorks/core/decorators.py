# core/decorators.py
from functools import wraps

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.utils.functional import SimpleLazyObject
from functools import wraps
from inspect import iscoroutinefunction
from django.http import HttpResponseForbidden, Http404
from simcore.models import Simulation

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

def simulation_required(kwarg_name: str = "simulation_id", owner_required: bool = True):
    """Decorator to fetch and authorize a Simulation object for a view.

    This decorator ensures that a Simulation with the given ID exists and,
    if `owner_required` is True, that the requesting user owns it. The
    resolved Simulation is attached to `request.simulation` for use inside
    the view. If the Simulation does not exist, a 404 is raised; if the user
    does not own it, a 403 is returned.

    Args:
        kwarg_name: The name of the URL kwarg that contains the simulation ID.
            Defaults to "simulation_id".
        owner_required: Whether to enforce ownership of the Simulation by
            the requesting user. Defaults to True.

    Returns:
        Callable: A decorated view function. The wrapped view will either
        return the original response or raise/return an appropriate
        Http404/HttpResponseForbidden.

    Raises:
        Http404: If the simulation kwarg is missing or the Simulation does
            not exist.
        HttpResponseForbidden: If `owner_required` is True and the Simulation
            does not belong to the requesting user.
    """
    def decorator(view_func):
        if iscoroutinefunction(view_func):
            @wraps(view_func)
            async def async_wrapper(request, *args, **kwargs):
                sim_id = kwargs.get(kwarg_name)
                if not sim_id:
                    raise Http404("Simulation id missing.")
                try:
                    simulation = await Simulation.objects.select_related("user").aget(id=sim_id)
                except Simulation.DoesNotExist:
                    raise Http404("Simulation not found.")
                if owner_required and request.user.is_authenticated and simulation.user_id != request.user.id:
                    return HttpResponseForbidden("This isn't your simulation.")
                request.simulation = simulation
                return await view_func(request, *args, **kwargs)
            return async_wrapper

        @wraps(view_func)
        def sync_wrapper(request, *args, **kwargs):
            sim_id = kwargs.get(kwarg_name)
            if not sim_id:
                raise Http404("Simulation id missing.")
            try:
                simulation = Simulation.objects.select_related("user").get(id=sim_id)
            except Simulation.DoesNotExist:
                raise Http404("Simulation not found.")
            if owner_required and request.user.is_authenticated and simulation.user_id != request.user.id:
                return HttpResponseForbidden("This isn't your simulation.")
            request.simulation = simulation
            return view_func(request, *args, **kwargs)
        return sync_wrapper
    return decorator