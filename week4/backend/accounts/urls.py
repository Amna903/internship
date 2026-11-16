from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf/", views.CsrfTokenView.as_view(), name="auth-csrf"),
    path("auth/signup/", views.SignupView.as_view(), name="auth-signup"),
    path("auth/user/login/", views.UserLoginView.as_view(), name="auth-user-login"),
    path("auth/user/refresh/", views.UserRefreshView.as_view(), name="auth-user-refresh"),
    path("auth/user/logout/", views.UserLogoutView.as_view(), name="auth-user-logout"),
]
