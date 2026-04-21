from __future__ import annotations

from typing import Any

from django.urls import reverse


def build_unreviewed_feedback_label(count: int) -> str:
    noun = "submission" if count == 1 else "submissions"
    return f"{count} unreviewed feedback {noun}"


def staff_feedback_awareness(request) -> dict[str, Any]:
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_staff", False):
        return {}

    from .models import UserFeedback

    count = UserFeedback.objects.filter(is_reviewed=False, is_archived=False).count()
    url = f"{reverse('feedback:staff-list')}?reviewed=unreviewed"
    return {
        "unreviewed_feedback_count": count,
        "unreviewed_feedback_label": build_unreviewed_feedback_label(count),
        "unreviewed_feedback_url": url,
    }
