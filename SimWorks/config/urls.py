# config/urls.py

from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path
from strawberry.django.views import AsyncGraphQLView

from api.v1.api import api as api_v1
from config.schema import schema
from core import views as CoreViews

sitemaps = {
    # "apps": ProductSitemap,
}

urlpatterns = [
    path("", CoreViews.index, name="home"),
    path("admin/", admin.site.urls),
    # REST API v1
    path("api/v1/", api_v1.urls),
    # App routes
    path("", include("simulation.urls")),
    path("accounts/", include("accounts.urls")),
    path("chatlab/", include("chatlab.urls")),
    # GraphQL (deprecated - will be removed)
    path("graphql/", AsyncGraphQLView.as_view(schema=schema), name="graphql"),
    path(
        "robots.txt",
        CoreViews.RobotsView.as_view(content_type="text/plain"),
        name="robots",
    ),
    path(
        "sitemap.xml",
        sitemap,
        {"sitemaps": sitemaps},
        name="django.contrib.sitemaps.views.sitemap",
    ),
]
