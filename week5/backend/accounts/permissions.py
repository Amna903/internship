from rest_framework.permissions import BasePermission

from .models import User


class IsStandardUser(BasePermission):
    """Authenticated, active and holding the *user* role."""

    message = "Standard user access required."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.role == User.Role.USER)


class IsAdminRole(BasePermission):
    """Authenticated, active and holding the *admin* role. Checked server-side on every request."""

    message = "Admin access required."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active and user.role == User.Role.ADMIN)
