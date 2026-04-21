from allauth.account.forms import SignupForm
from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.accounts.services.invitations import (
    InvitationClaimError,
    get_invitation_by_token_for_claim,
    normalize_email,
)
from apps.billing.catalog import all_product_codes, get_product

from .models import Account, AccountMembership, Invitation, UserRole

User = get_user_model()


def product_access_bundle_choices(include_blank: bool = True):
    choices = [("", "No Product Access Bundle")] if include_blank else []
    choices.extend((code, get_product(code).display_name) for code in all_product_codes())
    return choices


class InvitationForm(forms.ModelForm):
    """Form for creating new invitations."""

    class Meta:
        model = Invitation
        fields = ["email"]


class StaffInvitationCreateForm(forms.Form):
    email = forms.EmailField(label="Email")
    first_name = forms.CharField(label="First name", max_length=100, required=False)
    membership_role = forms.CharField(
        initial=AccountMembership.Role.GENERAL_USER,
        widget=forms.HiddenInput,
    )
    product_code = forms.ChoiceField(
        label="Product Access Bundle",
        choices=product_access_bundle_choices,
        required=False,
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not getattr(user, "is_superuser", False):
            self.fields.pop("product_code")

    def clean_membership_role(self):
        return AccountMembership.Role.GENERAL_USER

    def clean_product_code(self):
        if "product_code" not in self.fields:
            return ""
        return self.cleaned_data.get("product_code") or ""


class ManualProductAccessGrantForm(forms.Form):
    account_id = forms.ChoiceField(label="Account")
    product_code = forms.ChoiceField(
        label="Product Access Bundle",
        choices=lambda: product_access_bundle_choices(include_blank=False),
    )

    def __init__(self, *args, user_obj=None, **kwargs):
        self.user_obj = user_obj
        super().__init__(*args, **kwargs)
        accounts = Account.objects.filter(
            Q(memberships__user=user_obj, memberships__ended_at__isnull=True)
            | Q(owner_user=user_obj, account_type=Account.AccountType.PERSONAL)
        ).distinct().order_by("name", "id")
        self.fields["account_id"].choices = [(str(account.id), account.name) for account in accounts]

    def clean_account_id(self):
        account_id = self.cleaned_data["account_id"]
        try:
            return Account.objects.get(pk=account_id)
        except Account.DoesNotExist:
            raise ValidationError("Select a valid account.") from None


class InvitationSignupForm(SignupForm):
    """
    Custom allauth signup form with invitation token and required fields.

    This form extends allauth's SignupForm to:
    - Add first_name, last_name, and UserRole fields
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
        queryset=UserRole.objects.all(),
        required=True,
        label="Profile Role",
        help_text="Select your profile role",
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
        self.invitation: Invitation | None = None
        super().__init__(*args, **kwargs)

        token = self.request.session.get("invitation_token") if self.request else ""
        if token:
            self.fields["invitation_token"].initial = token
            self.fields["invitation_token"].widget.attrs["readonly"] = True
            self.fields["invitation_token"].required = False
            try:
                self.invitation = get_invitation_by_token_for_claim(token)
            except (Invitation.DoesNotExist, InvitationClaimError):
                self.invitation = None

        if self.invitation is not None:
            if self.invitation.email and "email" in self.fields:
                self.fields["email"].initial = self.invitation.email
                self.fields["email"].widget.attrs["readonly"] = True
            if self.invitation.first_name:
                self.fields["first_name"].initial = self.invitation.first_name

    def clean_invitation_token(self):
        """Validate invitation token from form or session."""
        # Try to get token from form first, then session
        token = self.cleaned_data.get("invitation_token")
        if not token and self.request:
            token = self.request.session.get("invitation_token")

        if not token:
            raise ValidationError("An invitation token is required to sign up.")

        try:
            invitation = get_invitation_by_token_for_claim(token)
        except Invitation.DoesNotExist:
            raise ValidationError("Invalid invitation token.") from None
        except InvitationClaimError as exc:
            raise ValidationError(str(exc)) from exc

        # Store for use in save()
        self.invitation = invitation
        self.cleaned_data["invitation_obj"] = invitation

        # Ensure token is in session for the adapter
        if self.request:
            self.request.session["invitation_token"] = token

        return token

    def clean(self):
        cleaned_data = super().clean()
        invitation = self.invitation or cleaned_data.get("invitation_obj")
        email = normalize_email(cleaned_data.get("email"))
        if invitation is not None and invitation.email and email != normalize_email(invitation.email):
            self.add_error("email", "Use the email address this invitation was sent to.")
        if email and User.objects.filter(email__iexact=email).exists():
            self.add_error(
                "email",
                "An account already exists for this email. Log in to accept the invitation.",
            )
        return cleaned_data

    def get_invitation(self) -> Invitation | None:
        return self.invitation

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
