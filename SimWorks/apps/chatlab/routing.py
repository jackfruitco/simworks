from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/v1/chatlab/$", consumers.ChatConsumer.as_asgi()),
]
