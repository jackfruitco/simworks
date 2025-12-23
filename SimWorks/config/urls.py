# config/urls.py

from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include
from django.urls import path
from strawberry.django.views import AsyncGraphQLView

from config.schema import schema
from core import views as CoreViews

sitemaps = {
    # "apps": ProductSitemap,
}

urlpatterns = [
    path("", CoreViews.index, name="home"),
    path("admin/", admin.site.urls),
    path("", include("simulation.urls")),
    path("accounts/", include("accounts.urls")),
    path("chatlab/", include("chatlab.urls")),
    path('graphql/', AsyncGraphQLView.as_view(schema=schema), name='graphql'),
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
