from django.urls import path

from . import views

urlpatterns = [
    path("agent/run/", views.AgentRunView.as_view(), name="agent-run"),
    path("agent/actions/<uuid:action_id>/", views.ActionView.as_view(), name="agent-action"),
    path("agent/actions/<uuid:action_id>/confirm/", views.ActionConfirmView.as_view(), name="agent-action-confirm"),
    path("agent/actions/<uuid:action_id>/decline/", views.ActionDeclineView.as_view(), name="agent-action-decline"),
]
