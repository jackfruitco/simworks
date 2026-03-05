"""
Django-allauth adapter for invitation-based signup.

This adapter integrates the invitation system with allauth's signup flow,
ensuring that users can only sign up with a valid invitation token.
"""

from allauth.account.adapter import DefaultAccountAdapter
from django.http import HttpRequest

from .models import Invitation


class InvitationAccountAdapter(DefaultAccountAdapter):
    """
    Custom allauth adapter that enforces invitation-only signup.

    Features:
    - Checks for invitation token in session
    - Validates token is not claimed or expired
    - Marks invitation as claimed after successful signup
    - Works with both email/password AND social auth signups
    """

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        """
        Check if signup is allowed.

        Returns True only if a valid invitation token exists in the session.
        This applies to BOTH regular signup and social auth signup.
        """
        invitation_token = request.session.get("invitation_token")

        if not invitation_token:
            return False

        try:
            invitation = Invitation.objects.get(token=invitation_token, is_claimed=False)
            return not invitation.is_expired
        except Invitation.DoesNotExist:
            return False

    def save_user(self, request, user, form, commit=True):
        """Save the user and mark invitation as claimed.

        This is called after successful signup (both email/password and social auth).
        """
        user = super().save_user(request, user, form, commit=False)

        # If we have a signup form, populate required custom fields BEFORE saving.
        # (Your User.role is NOT NULL, so the first save must include it.)
        if form is not None and hasattr(form, "cleaned_data"):
            cd = form.cleaned_data
            if "first_name" in cd:
                user.first_name = cd.get("first_name") or ""
            if "last_name" in cd:
                user.last_name = cd.get("last_name") or ""
            if "role" in cd and cd.get("role") is not None:
                user.role = cd["role"]

        if commit:
            user.save()

            # Mark invitation as claimed
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
                    # Clear the token from session regardless
                    request.session.pop("invitation_token", None)

        return user

    def clean_email(self, email):
        """
        Validate the email address.

        Override this if you want custom email validation logic.
        """
        return super().clean_email(email)

    def get_login_redirect_url(self, request):
        """
        Redirect after successful login.

        Can be overridden to provide custom redirect logic based on user role.
        """
        return super().get_login_redirect_url(request)
