from __future__ import annotations

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .forms import FeedbackBulkActionForm, FeedbackRemarkForm, FeedbackStatusForm
from .models import FeedbackAuditEvent, FeedbackRemark, UserFeedback
from .services import FeedbackQueryService, FeedbackWorkflowService


def _detail_redirect(feedback: UserFeedback):
    return redirect("feedback:staff-detail", feedback_id=feedback.pk)


@staff_member_required
@require_http_methods(["GET", "POST"])
def staff_feedback_list(request):
    query_service = FeedbackQueryService()
    workflow_service = FeedbackWorkflowService()

    if request.method == "POST":
        form = FeedbackBulkActionForm(request.POST)
        if form.is_valid():
            selected_ids = [item.pk for item in form.cleaned_data["feedback_ids"]]
            allowed_feedback = query_service.staff_inbox_queryset(request.GET).filter(
                pk__in=selected_ids
            )
            count = workflow_service.bulk_update(
                allowed_feedback,
                request.user,
                form.cleaned_data["action"],
            )
            messages.success(request, f"Updated {count} feedback item{'s' if count != 1 else ''}.")
        else:
            messages.error(request, "Select at least one feedback item and a valid action.")
        url = reverse("feedback:staff-list")
        if request.GET.urlencode():
            url = f"{url}?{request.GET.urlencode()}"
        return redirect(url)

    qs = query_service.staff_inbox_queryset(request.GET)
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    context = {
        "page_obj": page_obj,
        "feedback_items": page_obj.object_list,
        "analytics": query_service.analytics(),
        "categories": UserFeedback.Category.choices,
        "statuses": UserFeedback.Status.choices,
        "platforms": UserFeedback.ClientPlatform.choices,
        "bulk_form": FeedbackBulkActionForm(),
        "querystring": request.GET.urlencode(),
    }
    return render(request, "feedback/staff/list.html", context)


@staff_member_required
def staff_feedback_detail(request, feedback_id: int):
    feedback = get_object_or_404(
        UserFeedback.objects.select_related(
            "user",
            "account",
            "simulation",
            "conversation",
            "reviewed_by",
            "archived_by",
        ),
        pk=feedback_id,
    )
    context = {
        "feedback": feedback,
        "status_form": FeedbackStatusForm(initial={"status": feedback.status}),
        "remark_form": FeedbackRemarkForm(),
        "remarks": FeedbackRemark.objects.select_related("author").filter(feedback=feedback),
        "audit_events": FeedbackAuditEvent.objects.select_related("actor").filter(
            feedback=feedback
        ),
    }
    return render(request, "feedback/staff/detail.html", context)


@staff_member_required
@require_POST
def mark_reviewed(request, feedback_id: int):
    feedback = get_object_or_404(UserFeedback, pk=feedback_id)
    FeedbackWorkflowService().mark_reviewed(feedback, request.user)
    messages.success(request, "Feedback marked reviewed.")
    return _detail_redirect(feedback)


@staff_member_required
@require_POST
def set_status(request, feedback_id: int):
    feedback = get_object_or_404(UserFeedback, pk=feedback_id)
    form = FeedbackStatusForm(request.POST)
    if form.is_valid():
        FeedbackWorkflowService().set_status(feedback, form.cleaned_data["status"], request.user)
        messages.success(request, "Feedback status updated.")
    else:
        messages.error(request, "Choose a valid feedback status.")
    return _detail_redirect(feedback)


@staff_member_required
@require_POST
def archive(request, feedback_id: int):
    feedback = get_object_or_404(UserFeedback, pk=feedback_id)
    FeedbackWorkflowService().archive(feedback, request.user)
    messages.success(request, "Feedback archived.")
    return _detail_redirect(feedback)


@staff_member_required
@require_POST
def unarchive(request, feedback_id: int):
    feedback = get_object_or_404(UserFeedback, pk=feedback_id)
    FeedbackWorkflowService().unarchive(feedback, request.user)
    messages.success(request, "Feedback unarchived.")
    return _detail_redirect(feedback)


@staff_member_required
@require_POST
def add_remark(request, feedback_id: int):
    feedback = get_object_or_404(UserFeedback, pk=feedback_id)
    form = FeedbackRemarkForm(request.POST)
    if form.is_valid():
        FeedbackWorkflowService().add_remark(feedback, request.user, form.cleaned_data["body"])
        messages.success(request, "Developer team remark added.")
    else:
        messages.error(request, "Developer team remark cannot be blank.")
    return _detail_redirect(feedback)
