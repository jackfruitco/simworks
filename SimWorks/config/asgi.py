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

from config.logging import get_logger

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

logger = get_logger(__name__)

django_asgi_app = get_asgi_application()

from apps.chatlab.routing import websocket_urlpatterns as chatlab_ws  # noqa: E402
from apps.common.routing import websocket_urlpatterns as core_ws  # noqa: E402
from apps.common.ws_auth import SessionOrJWTAuthMiddlewareStack  # noqa: E402
from django.conf import settings  # noqa: E402


def _decode_header_value(value):
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return repr(value)


class LoggingWebSocketGate:
    """Diagnostic wrapper around the websocket app chain.

    Logs the incoming websocket scope before the inner middleware stack runs,
    and logs any websocket.close emitted during handshake so 403/close behavior
    is visible from ASGI entry.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        print("ASGI WS GATE HIT", scope.get("path"), scope.get("headers"))

        if scope.get("type") != "websocket":
            return await self.app(scope, receive, send)

        headers = {
            _decode_header_value(key).lower(): _decode_header_value(value)
            for key, value in scope.get("headers", [])
        }

        logger.info(
            "asgi.websocket.scope",
            path=scope.get("path"),
            client=scope.get("client"),
            server=scope.get("server"),
            scheme=scope.get("scheme"),
            root_path=scope.get("root_path"),
            subprotocols=scope.get("subprotocols", []),
            allowed_hosts=list(getattr(settings, "ALLOWED_HOSTS", [])),
            host=headers.get("host"),
            origin=headers.get("origin"),
            user_agent=headers.get("user-agent"),
            upgrade=headers.get("upgrade"),
            connection=headers.get("connection"),
            sec_websocket_version=headers.get("sec-websocket-version"),
            sec_websocket_protocol=headers.get("sec-websocket-protocol"),
            x_forwarded_for=headers.get("x-forwarded-for"),
            x_forwarded_proto=headers.get("x-forwarded-proto"),
            x_forwarded_host=headers.get("x-forwarded-host"),
            x_forwarded_port=headers.get("x-forwarded-port"),
            x_account_uuid=headers.get("x-account-uuid"),
            x_correlation_id=headers.get("x-correlation-id"),
            header_names=sorted(headers.keys()),
        )

        async def logging_send(message):
            print("ASGI WS SEND", message)

            if message.get("type") == "websocket.close":
                logger.warning(
                    "asgi.websocket.close",
                    path=scope.get("path"),
                    code=message.get("code"),
                    reason=message.get("reason"),
                    host=headers.get("host"),
                    origin=headers.get("origin"),
                    x_forwarded_proto=headers.get("x-forwarded-proto"),
                    x_forwarded_host=headers.get("x-forwarded-host"),
                    x_forwarded_port=headers.get("x-forwarded-port"),
                    x_account_uuid=headers.get("x-account-uuid"),
                    x_correlation_id=headers.get("x-correlation-id"),
                )
            await send(message)

        return await self.app(scope, receive, logging_send)


websocket_application = LoggingWebSocketGate(
    SessionOrJWTAuthMiddlewareStack(URLRouter(chatlab_ws + core_ws))
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": websocket_application,
    }
)
