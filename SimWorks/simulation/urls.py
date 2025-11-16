# simcore/urls.py
from django.urls import path

from . import views

app_name = "simcore"

urlpatterns = [
    path(
        "simulation/<int:simulation_id>/download/transcript/<str:format_type>",
        views.download_simulation_transcript,
        name="download_simulation_transcript",
    ),
    path(
        "tools/<str:tool_name>/refresh/<int:simulation_id>/",
        views.refresh_tool,
        name="refresh_tool",
    ),
    path(
        "tools/<str:tool_name>/checksum/<int:simulation_id>/",
        views.tool_checksum,
        name="tool_checksum",
    ),
    path(
        "simulation/<int:simulation_id>/orders/sign-orders/",
        views.sign_orders,
        name="sign_orders",
    ),
]
