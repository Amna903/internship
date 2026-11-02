from django.urls import path

from . import views

urlpatterns = [
    path("monitoring/", views.MonitoringView.as_view(), name="monitoring"),
    path("audit/overview/", views.AuditOverviewView.as_view(), name="audit-overview"),
    path("ops/", views.OpsView.as_view(), name="ops"),
]
