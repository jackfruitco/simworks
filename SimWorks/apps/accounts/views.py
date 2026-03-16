from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import is_inviter
from apps.simcore.models import Simulation

from .forms import AvatarUploadForm, InvitationForm
from .models import Invitation

User = get_user_model()


@login_required
@user_passes_test(is_inviter)
def new_invite(request):
    if request.method == "POST":
        form = InvitationForm(request.POST)
        if form.is_valid():
            invitation = form.save(commit=False)
            invitation.invited_by = request.user
            invitation.save()
            # Optionally, send an email with the invitation token/link here.
            if request.headers.get("HX-Request"):
                return render(request, "accounts/invite_success.html", {"invite": invitation})
            return redirect(reverse("accounts:invite-success", kwargs={"token": invitation.token}))
    else:
        form = InvitationForm()
    return render(request, "accounts/invite_new.html", {"form": form})


@login_required
@user_passes_test(is_inviter)
def invite_success(request, token):
    invite = Invitation.objects.get(token=token)
    return render(request, "accounts/invite_success_page.html", {"invite": invite})


@login_required
@user_passes_test(is_inviter)
def list_invites(request):
    page_number = request.GET.get("page", 1)
    invitations = Invitation.objects.order_by("-created_at")

    claimed = request.GET.get("claimed")
    expired = request.GET.get("expired")
    invited_by_list = request.GET.getlist("invited_by")

    if claimed in ("true", "false"):
        invitations = invitations.filter(claimed=(claimed == "true"))

    if expired in ("true", "false"):
        now = timezone.now()
        if expired == "true":
            invitations = invitations.filter(expires_at__lt=now)
        else:
            invitations = invitations.filter(expires_at__gte=now)

    if invited_by_list:
        invitations = invitations.filter(invited_by__username__in=invited_by_list)

    paginator = Paginator(invitations, 10)
    page = paginator.get_page(page_number)
    view_mode = request.GET.get("view_mode", "list")

    context = {
        "invitations": page.object_list,
        "page": page,
        "view_mode": view_mode,
        "next_page": int(page_number) + 1 if page.has_next() else None,
        "inviter_choices": Invitation.objects.exclude(invited_by__isnull=True)
        .values_list("invited_by__email", flat=True)
        .distinct()
        .order_by("invited_by__email"),
    }

    if request.headers.get("HX-Request"):
        html = render_to_string("accounts/partials/invite_single.html", context, request=request)
        return HttpResponse(html)
    return render(request, "accounts/invite_list.html", context)


@login_required
def profile_view(request, user_id=None):
    """
    User profile view.
    - If user_id is None, show current user's profile
    - Users can only view their own profile (enforced)
    """
    if user_id is None:
        # Redirect to current user's profile
        return redirect("accounts:profile-detail", user_id=request.user.id)

    # Get the user object
    profile_user = get_object_or_404(User, id=user_id)

    # Access control: users can only view their own profile
    if profile_user.id != request.user.id:
        return HttpResponse("You can only view your own profile.", status=403)

    # Get social accounts
    social_accounts = SocialAccount.objects.filter(user=profile_user)
    connected_provider_ids = list(social_accounts.values_list("provider", flat=True))

    # Get simulation statistics
    total_simulations = Simulation.objects.filter(user=profile_user).count()
    completed_simulations = Simulation.objects.filter(
        user=profile_user, end_timestamp__isnull=False
    ).count()
    in_progress_simulations = total_simulations - completed_simulations

    # Calculate completion rate
    completion_rate = (
        (completed_simulations / total_simulations * 100) if total_simulations > 0 else 0
    )

    context = {
        "profile_user": profile_user,
        "social_accounts": social_accounts,
        "connected_provider_ids": connected_provider_ids,
        "total_simulations": total_simulations,
        "completed_simulations": completed_simulations,
        "in_progress_simulations": in_progress_simulations,
        "completion_rate": round(completion_rate, 1),
    }

    return render(request, "accounts/profile_detail.html", context)


_PROFILE_FIELD_MAX_LENGTH = {
    "first_name": 150,
    "last_name": 150,
    "bio": 500,
}


@login_required
@require_http_methods(["POST"])
def update_profile_field(request):
    """
    HTMX endpoint for inline profile field updates.
    Expects: field_name, field_value in POST data
    """
    field_name = request.POST.get("field_name")
    field_value = request.POST.get("field_value", "")

    # Whitelist allowed fields
    if field_name not in _PROFILE_FIELD_MAX_LENGTH:
        return JsonResponse({"error": "Invalid field"}, status=400)

    max_length = _PROFILE_FIELD_MAX_LENGTH[field_name]
    if len(field_value) > max_length:
        return JsonResponse({"error": f"Value too long (max {max_length} characters)"}, status=400)

    # Update the user field
    setattr(request.user, field_name, field_value)
    request.user.save(update_fields=[field_name])

    # Return updated value
    return JsonResponse({"success": True, "field_name": field_name, "field_value": field_value})


@login_required
@require_http_methods(["POST"])
def upload_avatar(request):
    """
    HTMX endpoint for avatar upload.
    Returns the updated avatar URL.
    """
    form = AvatarUploadForm(request.POST, request.FILES, instance=request.user)

    if form.is_valid():
        form.save()

        # Return the updated avatar URL for HTMX swap
        avatar_url = request.user.avatar_thumbnail.url if request.user.avatar else None

        if request.headers.get("HX-Request"):
            # Return HTML fragment with updated avatar
            html = render_to_string(
                "accounts/partials/_avatar_display.html",
                {"profile_user": request.user},
                request=request,
            )
            return HttpResponse(html)

        return JsonResponse({"success": True, "avatar_url": avatar_url})

    return JsonResponse({"error": form.errors}, status=400)


@login_required
def simulation_history_list(request):
    """
    Paginated simulation history with filtering and sorting.
    Supports HTMX infinite scroll.
    """
    # Get query parameters
    page = int(request.GET.get("page", 1))
    sort_by = request.GET.get("sort", "-start_timestamp")  # Default: newest first
    lab_type = request.GET.get("lab_type", "")
    status = request.GET.get("status", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")

    # Base queryset
    simulations = Simulation.objects.filter(user=request.user)

    # Apply filters
    if lab_type:
        # Lab type is determined by which session exists
        # For now, we'll filter by a hypothetical field or skip
        pass  # TODO: Add lab_type field to Simulation model if needed

    if status == "complete":
        simulations = simulations.filter(end_timestamp__isnull=False)
    elif status == "in_progress":
        simulations = simulations.filter(end_timestamp__isnull=True)

    if date_from:
        simulations = simulations.filter(start_timestamp__gte=date_from)

    if date_to:
        simulations = simulations.filter(start_timestamp__lte=date_to)

    # Apply sorting
    valid_sort_fields = [
        "start_timestamp",
        "-start_timestamp",
        "diagnosis",
        "-diagnosis",
        "end_timestamp",
        "-end_timestamp",
    ]
    if sort_by in valid_sort_fields:
        simulations = simulations.order_by(sort_by)
    else:
        simulations = simulations.order_by("-start_timestamp")

    # Paginate (20 per page for infinite scroll)
    paginator = Paginator(simulations, 20)
    page_obj = paginator.get_page(page)

    context = {
        "simulations": page_obj,
        "page": page_obj,
    }

    if request.headers.get("HX-Request"):
        # Return partial for infinite scroll
        html = render_to_string(
            "accounts/partials/_simulation_history_items.html", context, request=request
        )
        return HttpResponse(html)

    # Full page render (shouldn't happen in normal flow)
    return render(request, "accounts/partials/_simulation_history_tab.html", context)
