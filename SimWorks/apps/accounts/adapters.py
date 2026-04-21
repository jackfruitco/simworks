"""Django-allauth adapter for invitation-based signup and branded auth emails."""

from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core import context as allauth_context
from django.conf import settings
from django.http import HttpRequest

from apps.common.emailing.environment import (
    get_email_base_url,
    get_email_environment_label,
    is_staging_email_context,
)

from .models import Invitation
from .services.invitations import (
    InvitationClaimError,
    claim_invitation_for_user,
    get_invitation_by_token_for_claim,
)


class InvitationAccountAdapter(DefaultAccountAdapter):
    """Custom allauth adapter that enforces invitation-only signup."""

    _simworks_email_request: HttpRequest | None = None
    _simworks_environment_hint: str | None = None

    def _extract_environment_hint(self, context: dict | None) -> str | None:
        if not isinstance(context, dict):
            return None
        hint = context.get("environment_hint") or context.get("email_environment_hint")
        return hint if isinstance(hint, str) else None

    def _resolve_email_request(self, context: dict | None) -> HttpRequest | None:
        if isinstance(context, dict) and isinstance(context.get("request"), HttpRequest):
            return context["request"]
        if isinstance(allauth_context.request, HttpRequest):
            return allauth_context.request
        if isinstance(self.request, HttpRequest):
            return self.request
        return None

    def _build_email_context(
        self,
        request: HttpRequest | None,
        context: dict | None,
    ) -> dict:
        merged = dict(context or {})
        environment_hint = self._extract_environment_hint(context)
        merged.setdefault("site_name", getattr(settings, "SITE_NAME", "MedSim"))
        merged.setdefault("product_name", "MedSim")
        merged.setdefault("product_tagline", "MedSim by Jackfruit")
        merged.setdefault("support_email", settings.EMAIL_REPLY_TO)
        merged["is_staging"] = is_staging_email_context(
            request=request,
            environment_hint=environment_hint,
        )
        merged["environment_label"] = get_email_environment_label(
            request=request,
            environment_hint=environment_hint,
        )
        merged["email_base_url"] = get_email_base_url(
            request=request,
            environment_hint=environment_hint,
        )
        return merged

    def format_email_subject(self, subject: str) -> str:
        subject = " ".join(subject.splitlines()).strip()
        django_prefix = str(getattr(settings, "EMAIL_SUBJECT_PREFIX", ""))
        if django_prefix and not subject.startswith(django_prefix):
            subject = f"{django_prefix}{subject}"

        if is_staging_email_context(
            request=self._simworks_email_request,
            environment_hint=self._simworks_environment_hint,
        ):
            prefix = str(getattr(settings, "EMAIL_STAGING_SUBJECT_PREFIX", "")).strip()
            if prefix and not subject.startswith(prefix):
                return f"{prefix} {subject}"
        return subject

    def send_mail(self, template_prefix, email, context):
        request = self._resolve_email_request(context)
        previous_request = self._simworks_email_request
        previous_environment_hint = self._simworks_environment_hint
        self._simworks_email_request = request
        self._simworks_environment_hint = self._extract_environment_hint(context)
        try:
            return super().send_mail(
                template_prefix,
                email,
                self._build_email_context(request=request, context=context),
            )
        finally:
            self._simworks_email_request = previous_request
            self._simworks_environment_hint = previous_environment_hint

    def render_mail(self, template_prefix, email, context, headers=None):
        request = self._resolve_email_request(context)
        previous_request = self._simworks_email_request
        previous_environment_hint = self._simworks_environment_hint
        self._simworks_email_request = request
        self._simworks_environment_hint = self._extract_environment_hint(context)
        try:
            merged_context = self._build_email_context(request=request, context=context)
            msg = super().render_mail(template_prefix, email, merged_context, headers=headers)
            if settings.EMAIL_REPLY_TO:
                msg.reply_to = [settings.EMAIL_REPLY_TO]
            return msg
        finally:
            self._simworks_email_request = previous_request
            self._simworks_environment_hint = previous_environment_hint

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        invitation_token = request.session.get("invitation_token")

        if not invitation_token:
            return False

        try:
            get_invitation_by_token_for_claim(invitation_token)
            return True
        except (Invitation.DoesNotExist, InvitationClaimError):
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
                    invitation = get_invitation_by_token_for_claim(invitation_token)
                    claim_invitation_for_user(invitation=invitation, user=user, request=request)
                except (Invitation.DoesNotExist, InvitationClaimError):
                    pass
                finally:
                    request.session.pop("invitation_token", None)

        return user

    def clean_email(self, email):
        return super().clean_email(email)

    def get_login_redirect_url(self, request):
        return super().get_login_redirect_url(request)
