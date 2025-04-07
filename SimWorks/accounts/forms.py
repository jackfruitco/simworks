from django import forms

from .models import Invitation


class InvitationForm(forms.ModelForm):
    class Meta:
        model = Invitation
        fields = ["email"]  # Let the user optionally specify an email address
