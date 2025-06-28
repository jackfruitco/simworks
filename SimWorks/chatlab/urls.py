# chatlab/urls.py
from django.urls import path

from . import views

app_name = "chatlab"

urlpatterns = [
    path("", views.index, name="index"),
    path("simulation/create/", views.create_simulation, name="create_simulation"),
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
        "simulation/<int:simulation_id>/refresh/older-messages/",
        views.load_older_messages,
        name="load_older_messages",
    ),
    path(
        "simulation/<int:simulation_id>/end_timestamp/",
        views.end_simulation,
        name="end_simulation",
    ),
]
