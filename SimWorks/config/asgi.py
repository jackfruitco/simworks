"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/asgi/
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

from apps.chatlab.routing import websocket_urlpatterns as chatlab_ws  # noqa: E402
from apps.common.ws_auth import SessionOrJWTAuthMiddlewareStack  # noqa: E402
from apps.common.routing import websocket_urlpatterns as core_ws  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            SessionOrJWTAuthMiddlewareStack(URLRouter(chatlab_ws + core_ws))
        ),
    }
)
