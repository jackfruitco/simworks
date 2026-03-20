from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .services.deletion import UserDeletionService
from .services.export import build_user_export_payload


@require_GET
@login_required
def privacy_policy(request):
    return render(request, "privacy/policy.html")


@require_GET
@login_required
def export_user_data(request):
    return JsonResponse(build_user_export_payload(request.user), json_dumps_params={"indent": 2})


@login_required
def delete_account(request):
    if request.method == "GET":
        return render(request, "privacy/delete_account.html")
    confirmation = request.POST.get("confirmation", "")
    if confirmation != "DELETE":
        return HttpResponseBadRequest("Confirmation text must be DELETE")
    UserDeletionService.delete_user(request.user)
    return JsonResponse({"deleted": True})
