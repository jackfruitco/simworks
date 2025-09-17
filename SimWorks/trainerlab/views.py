import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods

from core.decorators import resolve_user
from trainerlab.utils import create_new_simulation


logger = logging.getLogger(__name__)


@login_required
@resolve_user
@require_http_methods(["GET", "POST"])
async def create_simulation(request):
    if request.method == "GET":
        return redirect("trainerlab:create_session", simulation_id=None)

    # Otherwise, request must be POST
    modifiers = request.POST.getlist("modifier")
    simulation = await create_new_simulation(user=request.user, modifiers=modifiers)
    return redirect("trainerlab:run_simulation", simulation_id=simulation.id)
