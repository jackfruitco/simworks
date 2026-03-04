from django.template.loader import render_to_string
import pytest


@pytest.mark.django_db
def test_login_page_renders_social_signin_buttons(client):
    response = client.get("/accounts/login/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Sign in with Apple" in content
    assert "Sign in with Google" in content
    assert "/accounts/apple/login/" in content
    assert "/accounts/google/login/" in content


@pytest.mark.django_db
def test_signup_page_renders_social_signup_buttons(client):
    response = client.get("/accounts/signup/")

    assert response.status_code == 200
    content = response.content.decode()
    assert "Sign up with Apple" in content
    assert "Sign up with Google" in content
    assert "/accounts/apple/login/?process=signup" in content
    assert "/accounts/google/login/?process=signup" in content


@pytest.mark.django_db
def test_social_button_partial_render_for_connect_context():
    apple_html = render_to_string(
        "accounts/partials/_social_auth_buttons.html",
        {
            "auth_context": "connect",
            "provider": "apple",
            "href": "/accounts/apple/login/?process=connect",
            "size": "sm",
        },
    )
    google_html = render_to_string(
        "accounts/partials/_social_auth_buttons.html",
        {
            "auth_context": "connect",
            "provider": "google",
            "href": "/accounts/google/login/?process=connect",
            "size": "sm",
        },
    )

    assert "Continue with Apple" in apple_html
    assert "icons/brands/apple-logo.svg" in apple_html
    assert 'aria-label="Continue with Apple"' in apple_html

    assert "Continue with Google" in google_html
    assert "icons/brands/google-g.svg" in google_html
    assert 'aria-label="Continue with Google"' in google_html
