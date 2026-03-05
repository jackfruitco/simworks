"""
Middleware for handling invitation tokens in the signup flow.

This middleware captures invitation tokens from URL parameters and stores them
in the session, making them available during the allauth signup process.
"""

from django.http import HttpRequest


class InvitationMiddleware:
    """
    Capture invitation tokens from URL and store in session.

    Usage:
        /accounts/signup/?invitation=abc123xyz

    The token is stored in request.session['invitation_token'] and used by
    the InvitationAccountAdapter to validate signup eligibility.

    This works for both:
    - Regular email/password signup
    - Social auth signup (Apple, Google, etc.)
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        # Check if invitation token is in URL parameters
        invitation_token = request.GET.get("invitation")

        if invitation_token:
            # Store in session for use during signup
            request.session["invitation_token"] = invitation_token

        response = self.get_response(request)
        return response
