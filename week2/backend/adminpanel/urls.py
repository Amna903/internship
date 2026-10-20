from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.AdminLoginView.as_view(), name="admin-login"),
    path("logout/", views.AdminLogoutView.as_view(), name="admin-logout"),
    path("me/", views.AdminMeView.as_view(), name="admin-me"),
    path("profiles/", views.AdminProfileListView.as_view(), name="admin-profile-list"),
    path("profiles/<int:pk>/", views.AdminProfileDetailView.as_view(), name="admin-profile-detail"),
    path("profiles/<int:pk>/deactivate/", views.AdminProfileDeactivateView.as_view(), name="admin-profile-deactivate"),
    path("profiles/<int:pk>/activate/", views.AdminProfileActivateView.as_view(), name="admin-profile-activate"),
    path("audit-events/", views.AdminAuditEventListView.as_view(), name="admin-audit-events"),
]
