from django.conf import settings
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from .health import health, ready

handler404 = "config.exceptions.not_found"
handler500 = "config.exceptions.server_error"



urlpatterns = [
    path("health/", health, name="liveness"),
    path("ready/", ready, name="readiness"),
    path("api/health/", health, name="health"),
    path("api/", include("accounts.urls")),
    path("api/", include("profiles.urls")),
    path("api/admin/", include("adminpanel.urls")),
    path("api/v1/", include("predictions.urls")),
    path("api/v1/", include("assistant.urls")),
    path("api/v1/", include("agent.urls")),
    path("api/v1/", include("monitoring.urls")),
]

if settings.ENABLE_API_DOCS:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    ]
