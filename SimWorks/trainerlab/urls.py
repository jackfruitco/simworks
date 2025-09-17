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

    # HTMX endpoints
    # path(
    #     "simulation/<int:simulation_id>/end_timestamp/",
    #     views.end_simulation,
    #     name="end_simulation",
    # ),
]
