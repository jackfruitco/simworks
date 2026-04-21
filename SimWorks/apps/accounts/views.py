from urllib.parse import urlencode

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import is_inviter, staff_required
from apps.accounts.services import get_personal_account_for_user
from apps.accounts.services.invitations import (
    claim_invitation_for_user,
    create_invitation,
    resend_invitation,
    revoke_invitation,
)
from apps.billing.catalog import get_product
from apps.billing.models import (
    BillingAccount,
    Entitlement,
    SeatAllocation,
    SeatAssignment,
    Subscription,
)
from apps.billing.services.entitlements import grant_manual_product_entitlement
from apps.simcore.access import get_simulation_queryset_for_request
from apps.simcore.models import Simulation

from .forms import (
    AvatarUploadForm,
    InvitationForm,
    ManualProductAccessGrantForm,
    StaffInvitationCreateForm,
)
from .models import Account, AccountAuditEvent, AccountMembership, Invitation, InvitationAuditEvent

User = get_user_model()


def _normalized_email(value: str | None) -> str:
    return (value or "").strip().lower()


def _invitation_status(invitation: Invitation) -> str:
    if invitation.revoked_at:
        return "revoked"
    if invitation.is_claimed:
        return "claimed"
    if invitation.is_expired:
        return "expired"
    if invitation.send_count:
        return "sent"
    return "pending"


def _product_display_name(product_code: str) -> str:
    if not product_code:
        return ""
    return get_product(product_code).display_name


def _entitlement_rows(queryset):
    rows = []
    for entitlement in queryset:
        rows.append(
            {
                "entitlement": entitlement,
                "product_name": _product_display_name(entitlement.product_code),
            }
        )
    return rows


def _active_entitlements():
    now = timezone.now()
    return Entitlement.objects.filter(status__in=[Entitlement.Status.ACTIVE, Entitlement.Status.SCHEDULED]).filter(
        Q(starts_at__isnull=True) | Q(starts_at__lte=now),
        Q(ends_at__isnull=True) | Q(ends_at__gte=now),
    )


@login_required
@user_passes_test(is_inviter)
def new_invite(request):
    if request.method == "POST":
        form = InvitationForm(request.POST)
        if form.is_valid():
            invitation = create_invitation(invited_by=request.user, email=form.cleaned_data["email"])
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
        invitations = invitations.filter(is_claimed=(claimed == "true"))

    if expired in ("true", "false"):
        now = timezone.now()
        if expired == "true":
            invitations = invitations.filter(expires_at__lt=now)
        else:
            invitations = invitations.filter(expires_at__gte=now)

    if invited_by_list:
        invitations = invitations.filter(invited_by__email__in=invited_by_list)

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


def invitation_accept(request, token):
    try:
        invitation = Invitation.objects.select_related("invited_by", "claimed_by").get(token=token)
    except Invitation.DoesNotExist:
        return render(request, "accounts/invitations/invalid.html", status=404)

    if invitation.revoked_at:
        return render(request, "accounts/invitations/invalid.html", {"invitation": invitation}, status=410)
    if invitation.is_claimed:
        return render(request, "accounts/invitations/claimed.html", {"invitation": invitation}, status=410)
    if invitation.is_expired:
        return render(request, "accounts/invitations/expired.html", {"invitation": invitation}, status=410)

    request.session["invitation_token"] = invitation.token
    if request.user.is_authenticated:
        try:
            claim_invitation_for_user(invitation=invitation, user=request.user, request=request)
        except ValidationError as exc:
            return render(
                request,
                "accounts/invitations/email_mismatch.html",
                {"invitation": invitation, "error": exc},
                status=403,
            )
        messages.success(request, "Invitation accepted.")
        return redirect("home")

    if invitation.email and User.objects.filter(email__iexact=invitation.email).exists():
        query = urlencode({"next": invitation.get_absolute_url})
        return redirect(f"{reverse('account_login')}?{query}")
    return redirect(reverse("account_signup"))


@staff_required
def invitation_dashboard_list(request):
    invitations = Invitation.objects.select_related(
        "invited_by",
        "claimed_by",
        "claimed_account",
    ).order_by("-created_at", "-id")
    query = (request.GET.get("q") or "").strip()
    status = request.GET.get("status") or ""
    has_email = request.GET.get("has_email") or ""
    has_bundle = request.GET.get("has_bundle") or ""
    inviter = request.GET.get("inviter") or ""
    created_from = request.GET.get("created_from") or ""
    created_to = request.GET.get("created_to") or ""
    now = timezone.now()

    if query:
        invitations = invitations.filter(
            Q(email__icontains=query)
            | Q(token__icontains=query)
            | Q(invited_by__email__icontains=query)
            | Q(claimed_by__email__icontains=query)
        )
    if status == "pending":
        invitations = invitations.filter(
            is_claimed=False,
            revoked_at__isnull=True,
            send_count=0,
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
    elif status == "sent":
        invitations = invitations.filter(
            is_claimed=False,
            revoked_at__isnull=True,
            send_count__gt=0,
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
    elif status == "claimed":
        invitations = invitations.filter(is_claimed=True)
    elif status == "expired":
        invitations = invitations.filter(
            is_claimed=False,
            revoked_at__isnull=True,
            expires_at__lt=now,
        )
    elif status == "revoked":
        invitations = invitations.filter(revoked_at__isnull=False)
    if has_email == "true":
        invitations = invitations.exclude(email__isnull=True).exclude(email="")
    elif has_email == "false":
        invitations = invitations.filter(Q(email__isnull=True) | Q(email=""))
    if has_bundle == "true":
        invitations = invitations.exclude(product_code="")
    elif has_bundle == "false":
        invitations = invitations.filter(product_code="")
    if inviter:
        invitations = invitations.filter(invited_by_id=inviter)
    if created_from:
        invitations = invitations.filter(created_at__date__gte=created_from)
    if created_to:
        invitations = invitations.filter(created_at__date__lte=created_to)

    rows = [{"invitation": invitation, "status": _invitation_status(invitation)} for invitation in invitations]
    page = Paginator(rows, 25).get_page(request.GET.get("page", 1))
    context = {
        "page": page,
        "rows": page.object_list,
        "status": status,
        "query": query,
        "has_email": has_email,
        "has_bundle": has_bundle,
        "inviter": inviter,
        "created_from": created_from,
        "created_to": created_to,
        "inviter_choices": User.objects.filter(sent_invitations__isnull=False)
        .distinct()
        .order_by("email"),
    }
    return render(request, "accounts/staff/invitations/list.html", context)


@staff_required
def invitation_dashboard_detail(request, invitation_id):
    invitation = get_object_or_404(
        Invitation.objects.select_related("invited_by", "claimed_by", "claimed_account"),
        pk=invitation_id,
    )
    membership = None
    account_events = []
    entitlement_rows = []
    if invitation.claimed_account_id and invitation.claimed_by_id:
        membership = (
            AccountMembership.objects.filter(
                account=invitation.claimed_account,
                user=invitation.claimed_by,
                ended_at__isnull=True,
            )
            .order_by("-created_at")
            .first()
        )
        account_events = AccountAuditEvent.objects.filter(account=invitation.claimed_account)[:10]
        entitlement_rows = _entitlement_rows(
            Entitlement.objects.filter(account=invitation.claimed_account).order_by("-created_at")
        )
    context = {
        "invitation": invitation,
        "status": _invitation_status(invitation),
        "membership": membership,
        "entitlement_rows": entitlement_rows,
        "invitation_events": InvitationAuditEvent.objects.filter(invitation=invitation)[:10],
        "account_events": account_events,
    }
    return render(request, "accounts/staff/invitations/detail.html", context)


@staff_required
def invitation_dashboard_create(request):
    if request.method == "POST":
        form = StaffInvitationCreateForm(request.POST, user=request.user)
        if form.is_valid():
            invitation = create_invitation(
                invited_by=request.user,
                email=form.cleaned_data["email"],
                first_name=form.cleaned_data.get("first_name") or "",
                product_code=form.cleaned_data.get("product_code") or "",
                membership_role=form.cleaned_data["membership_role"],
            )
            messages.success(request, "Invitation created and queued for delivery.")
            return redirect("staff:invitation-detail", invitation_id=invitation.id)
    else:
        form = StaffInvitationCreateForm(user=request.user)
    return render(request, "accounts/staff/invitations/form.html", {"form": form})


@staff_required
@require_http_methods(["POST"])
def invitation_dashboard_resend(request, invitation_id):
    invitation = get_object_or_404(Invitation, pk=invitation_id)
    try:
        invitation = resend_invitation(invitation=invitation, resent_by=request.user)
        messages.success(request, "Invitation resent.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("staff:invitation-detail", invitation_id=invitation.id)


@staff_required
@require_http_methods(["POST"])
def invitation_dashboard_revoke(request, invitation_id):
    invitation = get_object_or_404(Invitation, pk=invitation_id)
    try:
        invitation = revoke_invitation(invitation=invitation, revoked_by=request.user)
        messages.success(request, "Invitation revoked.")
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    return redirect("staff:invitation-detail", invitation_id=invitation.id)


@staff_required
def user_dashboard_list(request):
    users = User.objects.select_related("active_account", "role").order_by("email")
    query = (request.GET.get("q") or "").strip()
    active = request.GET.get("active") or ""
    staff = request.GET.get("staff") or ""
    has_entitlement = request.GET.get("has_entitlement") or ""
    has_membership = request.GET.get("has_membership") or ""
    invited = request.GET.get("invited") or ""

    if query:
        users = users.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    if active in ("true", "false"):
        users = users.filter(is_active=(active == "true"))
    if staff in ("true", "false"):
        users = users.filter(is_staff=(staff == "true"))
    if has_membership == "true":
        users = users.filter(account_memberships__ended_at__isnull=True).distinct()
    elif has_membership == "false":
        users = users.exclude(account_memberships__ended_at__isnull=True).distinct()
    if has_entitlement == "true":
        users = users.filter(
            Q(entitlements__status=Entitlement.Status.ACTIVE)
            | Q(owned_accounts__entitlements__status=Entitlement.Status.ACTIVE)
        ).distinct()
    elif has_entitlement == "false":
        users = users.exclude(
            Q(entitlements__status=Entitlement.Status.ACTIVE)
            | Q(owned_accounts__entitlements__status=Entitlement.Status.ACTIVE)
        ).distinct()
    if invited == "true":
        users = users.filter(Q(invitation__isnull=False) | Q(sent_invitations__isnull=False)).distinct()
    elif invited == "false":
        users = users.filter(invitation__isnull=True, sent_invitations__isnull=True).distinct()

    page = Paginator(users, 25).get_page(request.GET.get("page", 1))
    rows = []
    active_entitlements = _active_entitlements()
    for user in page.object_list:
        accounts = Account.objects.filter(
            Q(owner_user=user, account_type=Account.AccountType.PERSONAL)
            | Q(memberships__user=user, memberships__ended_at__isnull=True)
        ).distinct()
        product_names = sorted(
            {
                _product_display_name(entitlement.product_code)
                for entitlement in active_entitlements.filter(
                    Q(account__in=accounts) | Q(subject_user=user)
                )
            }
        )
        rows.append({"user_obj": user, "product_names": product_names})
    context = {
        "page": page,
        "rows": rows,
        "query": query,
        "active": active,
        "staff": staff,
        "has_entitlement": has_entitlement,
        "has_membership": has_membership,
        "invited": invited,
    }
    return render(request, "accounts/staff/users/list.html", context)


@staff_required
def user_dashboard_detail(request, user_id):
    user_obj = get_object_or_404(User.objects.select_related("role", "active_account"), pk=user_id)
    if request.method == "POST":
        if not request.user.is_superuser:
            return HttpResponse("Superuser access required.", status=403)
        grant_form = ManualProductAccessGrantForm(request.POST, user_obj=user_obj)
        if grant_form.is_valid():
            account = grant_form.cleaned_data["account_id"]
            product_code = grant_form.cleaned_data["product_code"]
            entitlement = grant_manual_product_entitlement(
                user_obj,
                account,
                product_code,
                source_ref=f"manual:staff:{user_obj.pk}:{account.pk}:{product_code}",
            )
            AccountAuditEvent.objects.create(
                account=account,
                actor_user=request.user,
                event_type="entitlement.manual_granted",
                target_type="entitlement",
                target_ref=str(entitlement.uuid),
                metadata={"user_id": user_obj.id, "product_code": product_code},
            )
            messages.success(request, "Product Access Bundle granted.")
            return redirect("staff:user-detail", user_id=user_obj.id)
    else:
        grant_form = ManualProductAccessGrantForm(user_obj=user_obj)

    memberships = AccountMembership.objects.filter(user=user_obj).select_related("account").order_by("account__name")
    accounts = Account.objects.filter(
        Q(owner_user=user_obj, account_type=Account.AccountType.PERSONAL)
        | Q(memberships__user=user_obj)
    ).distinct()
    entitlements = Entitlement.objects.filter(Q(account__in=accounts) | Q(subject_user=user_obj)).select_related(
        "account",
        "subject_user",
    ).order_by("-created_at")
    context = {
        "user_obj": user_obj,
        "email_addresses": EmailAddress.objects.filter(user=user_obj).order_by("-primary", "email"),
        "personal_account": Account.objects.filter(
            owner_user=user_obj,
            account_type=Account.AccountType.PERSONAL,
        ).first(),
        "memberships": memberships,
        "entitlement_rows": _entitlement_rows(entitlements),
        "seat_assignments": SeatAssignment.objects.filter(user=user_obj).select_related("account"),
        "sent_invitations": Invitation.objects.filter(invited_by=user_obj).order_by("-created_at")[:20],
        "claimed_invitations": Invitation.objects.filter(claimed_by=user_obj).order_by("-created_at")[:20],
        "subscriptions": Subscription.objects.filter(account__in=accounts).select_related("account"),
        "audit_events": AccountAuditEvent.objects.filter(account__in=accounts)[:20],
        "grant_form": grant_form,
    }
    return render(request, "accounts/staff/users/detail.html", context)


@staff_required
def account_dashboard_list(request):
    accounts = Account.objects.select_related("owner_user").annotate(
        active_memberships_count=Count(
            "memberships",
            filter=Q(memberships__status=AccountMembership.Status.ACTIVE, memberships__ended_at__isnull=True),
        )
    ).order_by("name", "id")
    query = (request.GET.get("q") or "").strip()
    account_type = request.GET.get("type") or ""
    if query:
        accounts = accounts.filter(
            Q(name__icontains=query)
            | Q(slug__icontains=query)
            | Q(owner_user__email__icontains=query)
        )
    if account_type:
        accounts = accounts.filter(account_type=account_type)
    page = Paginator(accounts, 25).get_page(request.GET.get("page", 1))
    rows = []
    active_entitlements = _active_entitlements()
    for account in page.object_list:
        product_names = sorted(
            {
                _product_display_name(entitlement.product_code)
                for entitlement in active_entitlements.filter(account=account)
            }
        )
        subscriptions = Subscription.objects.filter(account=account).order_by("-updated_at")[:3]
        rows.append({"account": account, "product_names": product_names, "subscriptions": subscriptions})
    context = {
        "page": page,
        "rows": rows,
        "query": query,
        "account_type": account_type,
        "account_types": Account.AccountType.choices,
    }
    return render(request, "accounts/staff/accounts/list.html", context)


@staff_required
def account_dashboard_detail(request, account_id):
    account = get_object_or_404(Account.objects.select_related("owner_user", "parent_account"), pk=account_id)
    context = {
        "account": account,
        "memberships": AccountMembership.objects.filter(account=account).select_related("user").order_by("user__email", "invite_email"),
        "entitlement_rows": _entitlement_rows(
            Entitlement.objects.filter(account=account).select_related("subject_user").order_by("-created_at")
        ),
        "seat_allocations": SeatAllocation.objects.filter(account=account).order_by("-effective_from"),
        "seat_assignments": SeatAssignment.objects.filter(account=account).select_related("user").order_by("-assigned_at"),
        "billing_accounts": BillingAccount.objects.filter(account=account).order_by("provider_type"),
        "subscriptions": Subscription.objects.filter(account=account).order_by("-updated_at"),
        "audit_events": AccountAuditEvent.objects.filter(account=account)[:25],
    }
    return render(request, "accounts/staff/accounts/detail.html", context)


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
    personal_account = get_personal_account_for_user(profile_user)
    personal_simulations = Simulation.objects.filter(account=personal_account)
    total_simulations = personal_simulations.count()
    completed_simulations = personal_simulations.filter(end_timestamp__isnull=False).count()
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
    simulations = get_simulation_queryset_for_request(request, request.user)

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
