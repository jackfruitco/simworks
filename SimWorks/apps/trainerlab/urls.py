# trainerlab/urls.py
from django.urls import path

from . import views

app_name = "trainerlab"

urlpatterns = [
    path("", views.index, name="index"),
    path("simulation/create/", views.create_simulation, name="create_simulation"),
    path(
        "simulation/<int:simulation_id>/run/",
        views.run_simulation,
        name="run_simulation",
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
