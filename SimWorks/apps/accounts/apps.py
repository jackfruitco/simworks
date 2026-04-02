from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        from django.db.models.signals import post_migrate

        from apps.accounts import signals  # noqa: F401

        post_migrate.connect(_seed_roles, sender=self)

        from config.settings_parsers import bool_from_env

        if bool_from_env("DJANGO_DEBUG") and bool_from_env("DJANGO_CREATE_DEV_USER"):
            post_migrate.connect(_auto_create_dev_user, sender=self)


def _seed_roles(sender, **kwargs):
    """Seed default roles and system users after migrations."""
    from django.core.management import call_command

    call_command("seed_roles", verbosity=0)


def _auto_create_dev_user(sender, **kwargs):
    """Auto-create the dev user after migrations when env vars are set."""
    from django.core.management import call_command

    call_command("create_dev_user", verbosity=0)
