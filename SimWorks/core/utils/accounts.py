# core/utils/accounts.py
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model


@sync_to_async
def aget_or_create_system_user():
    return get_or_create_system_user()

def get_or_create_system_user():
    """
    Returns the singleton System user for AI or system-generated actions.
    Creates the user and the 'System' UserRole if they do not exist.

    Note: Uses email-based lookup since the User model does not have a username field.
    System user email: system@simworks.local
    """
    from apps.accounts.models import UserRole

    User = get_user_model()
    role, _ = UserRole.objects.get_or_create(title="System")
    system_user, _ = User.objects.get_or_create(
        email="system@simworks.local",
        defaults={
            "first_name": "System",
            "is_active": False,
            "role": role,
        },
    )
    return system_user


def get_system_user(name="System", **defaults):
    """
    Lazy-loads a system user by email.
    By default, returns the user with email 'system@simworks.local'.
    Additional defaults (like first_name, is_active, role) can be passed.

    Note: Uses email-based lookup since the User model does not have a username field.
    Email format: {name.lower()}@simworks.local
    """
    from apps.accounts.models import UserRole

    User = get_user_model()
    email = f"{name.lower()}@simworks.local"
    defaults.setdefault("first_name", name)
    defaults.setdefault("is_active", False)

    # Ensure role is set (required field)
    if "role" not in defaults:
        role, _ = UserRole.objects.get_or_create(title=name)
        defaults["role"] = role

    user, _ = User.objects.get_or_create(email=email, defaults=defaults)
    return user
