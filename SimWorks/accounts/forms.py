from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Invitation


class InvitationForm(forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ["email"]  # Let the user optionally specify an email address


from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta

from .models import Invitation


class CustomUserCreationForm(UserCreationForm):
    # Extra field to capture the invitation token
    invitation_token = forms.CharField(
        max_length=64, required=True, help_text="Enter your invitation token."
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()  # This references your 'accounts.CustomUser'
        # Add invitation_token so it appears on the form
        fields = (
            "username",
            "email",
            "role",
            "first_name",
            "last_name",
            "invitation_token",
        )

    def clean_invitation_token(self):
        """Validate the invitation token is correct, unclaimed, and not expired."""
        token = self.cleaned_data.get("invitation_token")
        try:
            invitation = Invitation.objects.get(token=token, is_claimed=False)
        except Invitation.DoesNotExist:
            raise ValidationError("Invalid invitation token or already claimed.")

        if invitation.is_expired:
            raise ValidationError("This invitation token has expired.")

        # Temporarily store the invitation on cleaned_data for use in save()
        self.cleaned_data["invitation_obj"] = invitation
        return token

    def save(self, commit=True):
        user = super().save(commit=False)

        # Retrieve the invitation instance stored during clean
        invitation = self.cleaned_data.get("invitation_obj")
        if commit:
            user.save()
            if invitation:
                invitation.mark_as_claimed(user=user)

        return user
