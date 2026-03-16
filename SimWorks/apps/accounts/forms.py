from allauth.account.forms import SignupForm
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Invitation, UserRole

User = get_user_model()


class InvitationForm(forms.ModelForm):
    """Form for creating new invitations."""

    class Meta:
        model = Invitation
        fields = ["email"]


class InvitationSignupForm(SignupForm):
    """
    Custom allauth signup form with invitation token and required fields.

    This form extends allauth's SignupForm to:
    - Add first_name, last_name, and role fields
    - Display invitation token (read-only if from URL)
    - Allow manual token entry if not in session
    - Validate token before allowing signup
    """

    first_name = forms.CharField(
        max_length=150,
        required=True,
        label="First Name",
        widget=forms.TextInput(attrs={"placeholder": "First Name"}),
    )

    last_name = forms.CharField(
        max_length=150,
        required=True,
        label="Last Name",
        widget=forms.TextInput(attrs={"placeholder": "Last Name"}),
    )

    role = forms.ModelChoiceField(
        queryset=UserRole.objects.all(), required=True, label="Role", help_text="Select your role"
    )

    invitation_token = forms.CharField(
        max_length=64,
        required=False,  # Optional in form since it can come from session
        label="Invitation Token",
        widget=forms.TextInput(attrs={"placeholder": "Enter invitation token"}),
        help_text="Required to create an account",
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        if self.request and self.request.session.get("invitation_token"):
            token = self.request.session["invitation_token"]
            self.fields["invitation_token"].initial = token
            self.fields["invitation_token"].widget.attrs["readonly"] = True
            self.fields["invitation_token"].required = False

    def clean_invitation_token(self):
        """Validate invitation token from form or session."""
        # Try to get token from form first, then session
        token = self.cleaned_data.get("invitation_token")
        if not token and self.request:
            token = self.request.session.get("invitation_token")

        if not token:
            raise ValidationError("An invitation token is required to sign up.")

        try:
            with transaction.atomic():
                invitation = Invitation.objects.select_for_update().get(
                    token=token, is_claimed=False
                )
        except Invitation.DoesNotExist:
            raise ValidationError("Invalid invitation token or already claimed.") from None

        if invitation.is_expired:
            raise ValidationError("This invitation token has expired.")

        # Store for use in save()
        self.cleaned_data["invitation_obj"] = invitation

        # Ensure token is in session for the adapter
        if self.request:
            self.request.session["invitation_token"] = token

        return token

    def save(self, request):
        """Save user with additional fields."""
        user = super().save(request)

        # Set additional fields
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.role = self.cleaned_data["role"]
        user.save()

        # Note: Invitation claiming is handled by the adapter's save_user() method

        return user


class ProfileEditForm(forms.ModelForm):
    """Form for editing user profile information."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "bio"]
        widgets = {
            "first_name": forms.TextInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500",
                    "placeholder": "First Name",
                }
            ),
            "last_name": forms.TextInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500",
                    "placeholder": "Last Name",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500",
                    "placeholder": "Email",
                }
            ),
            "bio": forms.Textarea(
                attrs={
                    "class": "w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500",
                    "placeholder": "Tell us about yourself...",
                    "rows": 4,
                }
            ),
        }


class AvatarUploadForm(forms.ModelForm):
    """Form for uploading user avatar/profile photo."""

    class Meta:
        model = User
        fields = ["avatar"]
        widgets = {"avatar": forms.FileInput(attrs={"accept": "image/*", "class": "hidden"})}

    _ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "GIF", "WEBP"}

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar:
            # Validate file size (max 5MB)
            if avatar.size > 5 * 1024 * 1024:
                raise ValidationError("Image file too large ( > 5MB )")

            # Validate by reading file bytes, not by trusting the client-supplied
            # content_type header (which can be trivially spoofed).
            try:
                from PIL import Image

                avatar.seek(0)
                img = Image.open(avatar)
                img_format = img.format  # Read format before verify() exhausts stream
                img.verify()  # Validates image integrity (raises on corrupt/non-image)
                avatar.seek(0)
            except ValidationError:
                raise
            except Exception as exc:
                raise ValidationError("File must be a valid image.") from exc

            if img_format not in self._ALLOWED_IMAGE_FORMATS:
                raise ValidationError(
                    f"Unsupported image format '{img_format}'. "
                    f"Allowed formats: {', '.join(sorted(self._ALLOWED_IMAGE_FORMATS))}."
                )

        return avatar
