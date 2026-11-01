from django.urls import path

from . import views

urlpatterns = [
    path("assistant/status/", views.AssistantStatusView.as_view(), name="assistant-status"),
    path("assistant/ask/", views.AskView.as_view(), name="assistant-ask"),
    path("assistant/documents/", views.DocumentsView.as_view(), name="assistant-documents"),
    path("assistant/documents/<int:document_id>/approve/", views.DocumentApproveView.as_view(),
         name="assistant-document-approve"),
]
