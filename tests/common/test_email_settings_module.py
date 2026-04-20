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
            "POSTMARK_SERVER_TOKEN",
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


def test_email_settings_defaults_to_postmark_in_staging_when_token_present(reload_email_settings):
    settings_mod = reload_email_settings(
        {
            "DJANGO_DEBUG": "false",
            "EMAIL_ENVIRONMENT_NAME": "staging",
            "POSTMARK_SERVER_TOKEN": "postmark-token",
        }
    )

    assert settings_mod.EMAIL_BACKEND == "anymail.backends.postmark.EmailBackend"


def test_email_settings_raises_if_postmark_token_missing_outside_local(reload_email_settings):
    with pytest.raises(ValueError, match="POSTMARK_SERVER_TOKEN"):
        reload_email_settings(
            {
                "DJANGO_DEBUG": "false",
                "EMAIL_ENVIRONMENT_NAME": "production",
                "EMAIL_BACKEND": "anymail.backends.postmark.EmailBackend",
                "POSTMARK_SERVER_TOKEN": "",
            }
        )
