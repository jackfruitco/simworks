from __future__ import annotations

from django import forms

from .models import UserFeedback
from .services import FeedbackWorkflowService


class FeedbackStatusForm(forms.Form):
    status = forms.ChoiceField(
        choices=[
            (value, label)
            for value, label in UserFeedback.Status.choices
            if value != UserFeedback.Status.NEW
        ],
        required=True,
        widget=forms.Select(
            attrs={"class": "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"}
        ),
    )


class FeedbackRemarkForm(forms.Form):
    body = forms.CharField(
        label="Developer Team Remark",
        max_length=10_000,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "class": "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm",
            }
        ),
    )


class FeedbackBulkActionForm(forms.Form):
    action = forms.ChoiceField(
        choices=[
            ("mark_reviewed", "Mark reviewed"),
            ("mark_action_required", "Mark action required"),
            ("mark_no_action_required", "Mark no action required"),
            ("mark_planned", "Mark planned"),
            ("mark_resolved", "Mark resolved"),
            ("mark_duplicate", "Mark duplicate"),
            ("mark_wont_fix", "Mark won't fix"),
            ("archive", "Archive"),
        ],
        required=True,
        widget=forms.Select(
            attrs={"class": "rounded-lg border border-border bg-surface px-3 py-2 text-sm"}
        ),
    )
    feedback_ids = forms.ModelMultipleChoiceField(
        queryset=UserFeedback.objects.all(),
        required=True,
    )

    def clean_action(self):
        action = self.cleaned_data["action"]
        if action not in FeedbackWorkflowService.BULK_ACTIONS:
            raise forms.ValidationError("Unsupported bulk action.")
        return action
