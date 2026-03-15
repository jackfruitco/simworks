# chatlab/urls.py
from django.urls import path

from . import views

app_name = "chatlab"

urlpatterns = [
    path("", views.index, name="index"),
    path("simulation/create/", views.create_simulation, name="create_simulation"),
    path("api/modifier-selector/", views.modifier_selector, name="modifier_selector"),
    path(
        "simulation/<int:simulation_id>/run/",
        views.run_simulation,
        name="run_simulation",
    ),
    # HTMX endpoints
    path(
        "simulation/<int:simulation_id>/refresh/messages/",
        views.refresh_messages,
        name="refresh_messages",
    ),
    path(
        "simulation/<int:simulation_id>/refresh/metadata/current-checksum/",
        views.get_metadata_checksum,
        name="current_metadata_checksum",
    ),
    path(
        "simulation/<int:simulation_id>/refresh/messages/older/",
        views.load_older_messages,
        name="load_older_messages",
    ),
    path(
        "simulation/<int:simulation_id>/end_timestamp/",
        views.end_simulation,
        name="end_simulation",
    ),
    path(
        "simulation/<int:simulation_id>/message/<int:message_id>/",
        views.get_single_message,
        name="get_single_message",
    ),
    # Admin watch views
    path(
        "simulation/<int:simulation_id>/watch/",
        views.watch_simulation,
        name="watch_simulation",
    ),
    path(
        "simulation/<int:simulation_id>/watch/stream/",
        views.watch_stream,
        name="watch_stream",
    ),
    path(
        "simulation/<int:simulation_id>/watch/service-calls/",
        views.watch_service_calls,
        name="watch_service_calls",
    ),
]
