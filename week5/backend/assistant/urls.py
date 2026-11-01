from django.urls import path

from . import views

urlpatterns = [
    path("assistant/status/", views.AssistantStatusView.as_view(), name="assistant-status"),
    path("assistant/ask/", views.AskView.as_view(), name="assistant-ask"),
    path("assistant/documents/", views.DocumentsView.as_view(), name="assistant-documents"),
    path("assistant/documents/<int:document_id>/approve/", views.DocumentApproveView.as_view(),
         name="assistant-document-approve"),
    path("assistant/documents/<int:document_id>/versions/", views.DocumentVersionsView.as_view(),
         name="assistant-document-versions"),
    path("assistant/documents/<int:document_id>/versions/<int:number>/approve/", views.DocumentVersionApproveView.as_view(),
         name="assistant-version-approve"),
    path("assistant/documents/<int:document_id>/versions/<int:number>/reject/", views.DocumentVersionRejectView.as_view(),
         name="assistant-version-reject"),
    path("assistant/documents/<int:document_id>/retire/", views.DocumentRetireView.as_view(),
         name="assistant-document-retire"),
]
