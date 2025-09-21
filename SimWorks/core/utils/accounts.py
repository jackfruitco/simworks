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
        },
    )
    return system_user


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
