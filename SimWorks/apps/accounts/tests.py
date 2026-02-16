from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Invitation

User = get_user_model()


class InvitationTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Create a user with invitation privileges
        self.inviter = User.objects.create_user(
            username="inviter", password="password", email="inviter@example.com"
        )
        inviters_group, _ = Group.objects.get_or_create(name="Inviters")
        self.inviter.groups.add(inviters_group)
        self.inviter.save()

        # Create a non-inviter user
        self.non_inviter = User.objects.create_user(
            username="noninviter", password="password", email="noninviter@example.com"
        )

        # Login as inviter by default
        self.client.login(username="inviter", password="password")

    def test_invite_view_accessible_for_inviter(self):
        response = self.client.get(reverse("invite"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invite a User")

    def test_invite_view_forbidden_for_non_inviter(self):
        self.client.logout()
        self.client.login(username="noninviter", password="password")
        response = self.client.get(reverse("invite"))
        # Depending on your user_passes_test configuration,
        # you might receive a 403 Forbidden if the test fails.
        self.assertEqual(response.status_code, 403)

    def test_invitation_creation(self):
        data = {"email": "invitee@example.com"}
        response = self.client.post(reverse("invite"), data)
        self.assertEqual(response.status_code, 302)  # assuming redirect on success
        invitation = Invitation.objects.filter(email="invitee@example.com").first()
        self.assertIsNotNone(invitation)
        self.assertFalse(invitation.used)
        self.assertTrue(invitation.expires_at > timezone.now())


class SignupTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Create an invitation for testing signup
        self.invitation = Invitation.objects.create(
            email="newuser@example.com", expires_at=timezone.now() + timedelta(days=7)
        )

    def test_signup_with_valid_invitation(self):
        signup_url = reverse("signup") + f"?token={self.invitation.token}"
        response = self.client.get(signup_url)
        self.assertEqual(response.status_code, 200)
        signup_data = {
            "username": "newuser",
            "password1": "complexpassword123",
            "password2": "complexpassword123",
            "token": self.invitation.token,
        }
        response = self.client.post(reverse("signup"), signup_data)
        self.assertEqual(response.status_code, 302)  # Redirect on success
        user = User.objects.filter(username="newuser").first()
        self.assertIsNotNone(user)
        self.invitation.refresh_from_db()
        self.assertTrue(self.invitation.used)

    def test_signup_with_invalid_invitation(self):
        signup_data = {
            "username": "anotheruser",
            "password1": "complexpassword123",
            "password2": "complexpassword123",
            "token": "invalidtoken",
        }
        response = self.client.post(reverse("signup"), signup_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invitation token is invalid or expired.")
