from django.urls import path

from . import views

urlpatterns = [
    path("assistant/status/", views.AssistantStatusView.as_view(), name="assistant-status"),
]
