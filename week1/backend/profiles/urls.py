from django.urls import path

from . import views

urlpatterns = [
    path("profiles/me/", views.MeProfileView.as_view(), name="profile-me"),
]
