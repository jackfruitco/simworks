import importlib

import pytest


@pytest.fixture
def reload_email_settings(monkeypatch):
    def _load(env: dict[str, str | None]):
        for key in (
            "DJANGO_DEBUG",
            "EMAIL_ENVIRONMENT_NAME",
            "EMAIL_USE_CONSOLE_BACKEND",
            "EMAIL_BACKEND",
            "EMAIL_HOST_USER",
            "EMAIL_HOST_PASSWORD",
            "EMAIL_BASE_URL",
        ):
            monkeypatch.delenv(key, raising=False)

        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)

        import config.email_settings as email_settings

        return importlib.reload(email_settings)

    return _load


def test_email_settings_defaults_to_console_in_local_debug(reload_email_settings):
    settings_mod = reload_email_settings(
        {
            "DJANGO_DEBUG": "true",
            "EMAIL_ENVIRONMENT_NAME": "local",
        }
    )

    assert settings_mod.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"


def test_email_settings_defaults_to_smtp_in_staging_when_credentials_present(reload_email_settings):
    settings_mod = reload_email_settings(
        {
            "DJANGO_DEBUG": "false",
            "EMAIL_ENVIRONMENT_NAME": "staging",
            "EMAIL_HOST_USER": "noreply@icloud.example",
            "EMAIL_HOST_PASSWORD": "app-specific-password",
        }
    )

    assert settings_mod.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
    assert settings_mod.EMAIL_HOST == "smtp.mail.me.com"
    assert settings_mod.EMAIL_PORT == 587
    assert settings_mod.EMAIL_USE_TLS is True


def test_email_settings_flags_missing_smtp_credentials_outside_local(reload_email_settings):
    settings_mod = reload_email_settings(
        {
            "DJANGO_DEBUG": "false",
            "EMAIL_ENVIRONMENT_NAME": "production",
            "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "EMAIL_HOST_USER": "",
            "EMAIL_HOST_PASSWORD": "",
        }
    )

    assert settings_mod.REQUIRES_SMTP_CREDENTIALS is True
    assert settings_mod.SMTP_CREDENTIALS_CONFIGURED is False
