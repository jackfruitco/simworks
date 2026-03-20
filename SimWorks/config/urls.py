# config/urls.py

from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from api.v1.api import api as api_v1
from apps.common import views as CommonViews

sitemaps = {
    # "apps": ProductSitemap,
}

urlpatterns = [
    path("", CommonViews.index, name="home"),
    path("admin/", admin.site.urls),
    # REST API v1
    path("api/v1/", api_v1.urls),
    # App routes
    path("", include("apps.simcore.urls")),
    # Custom accounts URLs (must come before allauth to catch profile/invitations URLs)
    path("accounts/", include("apps.accounts.urls")),
    # Django-allauth URLs (login, signup, password reset, etc.)
    path("accounts/", include("allauth.urls")),
    path("chatlab/", include("apps.chatlab.urls")),
    path("trainerlab/", include("apps.trainerlab.urls")),
    path("privacy/", include("apps.privacy.urls")),
    path(
        "robots.txt",
        CommonViews.RobotsView.as_view(content_type="text/plain"),
        name="robots",
    ),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
]
