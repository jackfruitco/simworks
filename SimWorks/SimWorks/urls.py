from core import views as CoreViews
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include
from django.urls import path

sitemaps = {
    # "products": ProductSitemap,
}

urlpatterns = [
    path("", CoreViews.index, name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("ChatLab/", include("ChatLab.urls")),
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
