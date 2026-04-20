"""Django-allauth adapter for invitation-based signup and branded auth emails."""

from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.http import HttpRequest

from apps.common.emailing.environment import (
    get_email_base_url,
    get_email_environment_label,
    is_staging_email_context,
)

from .models import Invitation


class InvitationAccountAdapter(DefaultAccountAdapter):
    """Custom allauth adapter that enforces invitation-only signup."""

    _simworks_email_request: HttpRequest | None = None

    def _build_email_context(
        self,
        request: HttpRequest | None,
        context: dict | None,
    ) -> dict:
        merged = dict(context or {})
        merged.setdefault("site_name", getattr(settings, "SITE_NAME", "MedSim"))
        merged.setdefault("product_name", "MedSim")
        merged.setdefault("product_tagline", "MedSim by Jackfruit")
        merged.setdefault("support_email", settings.EMAIL_REPLY_TO)
        merged["is_staging"] = is_staging_email_context(request=request)
        merged["environment_label"] = get_email_environment_label(request=request)
        merged["email_base_url"] = get_email_base_url(request=request)
        return merged

    def format_email_subject(self, subject: str) -> str:
        subject = super().format_email_subject(subject)
        if is_staging_email_context(request=self._simworks_email_request):
            prefix = str(getattr(settings, "EMAIL_STAGING_SUBJECT_PREFIX", "")).strip()
            if prefix and not subject.startswith(prefix):
                return f"{prefix} {subject}"
        return subject

    def send_mail(self, template_prefix, email, context):
        request = None
        if isinstance(context, dict):
            request = context.get("request")

        self._simworks_email_request = request
        try:
            return super().send_mail(
                template_prefix,
                email,
                self._build_email_context(request=request, context=context),
            )
        finally:
            self._simworks_email_request = None

    def render_mail(self, template_prefix, email, context, headers=None):
        request = context.get("request") if isinstance(context, dict) else None
        merged_context = self._build_email_context(request=request, context=context)
        msg = super().render_mail(template_prefix, email, merged_context, headers=headers)
        if settings.EMAIL_REPLY_TO:
            msg.reply_to = [settings.EMAIL_REPLY_TO]
        return msg

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        invitation_token = request.session.get("invitation_token")

        if not invitation_token:
            return False

        try:
            invitation = Invitation.objects.get(token=invitation_token, is_claimed=False)
            return not invitation.is_expired
        except Invitation.DoesNotExist:
            return False

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)

        if form is not None and hasattr(form, "cleaned_data"):
            cleaned_data = form.cleaned_data
            if "first_name" in cleaned_data:
                user.first_name = cleaned_data.get("first_name") or ""
            if "last_name" in cleaned_data:
                user.last_name = cleaned_data.get("last_name") or ""
            if "role" in cleaned_data and cleaned_data.get("role") is not None:
                user.role = cleaned_data["role"]

        if commit:
            user.save()

            invitation_token = request.session.get("invitation_token")
            if invitation_token:
                try:
                    invitation = Invitation.objects.get(
                        token=invitation_token,
                        is_claimed=False,
                    )
                    invitation.mark_as_claimed(user=user)
                except Invitation.DoesNotExist:
                    pass
                finally:
                    request.session.pop("invitation_token", None)

        return user

    def clean_email(self, email):
        return super().clean_email(email)

    def get_login_redirect_url(self, request):
        return super().get_login_redirect_url(request)
