from accounts.decorators import is_inviter
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .forms import InvitationForm, CustomUserCreationForm
from .models import Invitation


def register(request, token=None):
    token = token or request.GET.get("token") or request.POST.get("token")
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("accounts:profile")
    else:
        # Pre-populate the invitation_token field if a token exists
        form = CustomUserCreationForm(initial={"invitation_token": token} if token else None)

    return render(request, "accounts/signup.html", {"form": form, "token": token})


@login_required
def profile(request):
    return render(request, "accounts/profile.html")


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
                return render(
                    request, "accounts/invite_success.html", {"invite": invitation}
                )
            return redirect(
                reverse("accounts:invite_success", kwargs={"token": invitation.token})
            )
    else:
        form = InvitationForm()
    return render(request, "accounts/invite_new.html", {"form": form})


@login_required
@user_passes_test(is_inviter)
def invite_success(request, token):
    invite = Invitation.objects.get(token=token)
    return render(request, "accounts/invite_success.html", {"invite": invite})


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
        .values_list("invited_by__username", flat=True)
        .distinct()
        .order_by("invited_by__username"),
    }

    if request.headers.get("HX-Request"):
        html = render_to_string(
            "accounts/partials/invite_single.html", context, request=request
        )
        return HttpResponse(html)
    return render(request, "accounts/invite_list.html", context)
