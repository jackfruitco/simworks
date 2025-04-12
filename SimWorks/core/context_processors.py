# core/context_processors.py

from django.conf import settings


def site_info(request):
    """
    Adds core site context to every template.

    This context processor expects that settings.SITE_ADMIN is a dictionary, for example:

        SITE_ADMIN = {
            "NAME": "John Doe",
            "EMAIL": "john.doe@example.com",
            # Additional keys as needed...
        }

    It also reads SITE_NAME from settings.
    """
    # Get the SITE_ADMIN dict if available, or use an empty dict as default.
    site_admin = getattr(settings, "SITE_ADMIN", {})
    return {
        "SITE_ADMIN": site_admin,
        "SITE_NAME": getattr(settings, "SITE_NAME", "My Site"),
    }