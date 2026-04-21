from django.urls import path

from . import views

app_name = "feedback"

urlpatterns = [
    path("", views.staff_feedback_list, name="staff-list"),
    path("<int:feedback_id>/", views.staff_feedback_detail, name="staff-detail"),
    path("<int:feedback_id>/mark-reviewed/", views.mark_reviewed, name="mark-reviewed"),
    path("<int:feedback_id>/set-status/", views.set_status, name="set-status"),
    path("<int:feedback_id>/archive/", views.archive, name="archive"),
    path("<int:feedback_id>/unarchive/", views.unarchive, name="unarchive"),
    path("<int:feedback_id>/remarks/", views.add_remark, name="add-remark"),
]
