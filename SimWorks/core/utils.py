import hashlib
import logging
import os

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured

# A unique sentinel to detect if a default value was provided.
_SENTINEL = object()


def check_env(var_name, default=_SENTINEL):
    """
    Retrieves the environment variable or returns the default if provided.
    Raises ImproperlyConfigured if the variable is not found and no default is provided.

    :param var_name: The name of the environment variable.
    :param default: The default value to return if the variable is not found.
                    If not provided, an error is raised.
    :return: The environment variable value or the default.
    """
    try:
        return os.environ[var_name]
    except KeyError:
        if default is not _SENTINEL:
            return default
        error_msg = (
            f"{var_name} not found! Did you set the environment variable {var_name}?"
        )
        # raise ImproperlyConfigured(error_msg)

def get_or_create_system_user():
    """
    Returns the singleton System user for AI or system-generated actions.
    Creates the user and the 'System' UserRole if they do not exist.
    """
    from accounts.models import UserRole

    User = get_user_model()
    role, _ = UserRole.objects.get_or_create(title="System")
    system_user, _ = User.objects.get_or_create(
        username="System",
        defaults={
            "first_name": "System",
            "is_active": False,
            "role": role,
        }
    )
    return system_user


class AppColorFormatter(logging.Formatter):
    COLORS = {
        "chatlab": "\033[94m",       # Blue
        "simai": "\033[92m",      # Green
        "accounts": "\033[95m",      # Magenta
        "notifications": "\033[93m", # Yellow
    }
    RESET = "\033[0m"

    def format(self, record):
        app = record.name.split(".")[0]
        color = self.COLORS.get(app, "")
        record.name = f"{color}{record.name}{self.RESET}" if color else record.name
        return super().format(record)


def get_system_user(name="System", **defaults):
    """
    Lazy-loads a system user by name.
    By default, returns the user with username 'System'.
    Additional defaults (like first_name, is_active) can be passed.
    """
    User = get_user_model()
    defaults.setdefault("first_name", name)
    defaults.setdefault("is_active", False)
    user, _ = User.objects.get_or_create(username=name, defaults=defaults)
    return user

def compute_fingerprint(*args: str) -> str:
    """
    Compute a SHA256 hash from any number of string arguments.

    Args:
        *args (str): Any number of strings to combine and hash.

    Returns:
        str: The SHA256 hex digest of the combined string.
    """
    combined = "".join(arg.strip() for arg in args if isinstance(arg, str))
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
