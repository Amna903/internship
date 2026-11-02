from rest_framework.authentication import SessionAuthentication


class AdminSessionAuthentication(SessionAuthentication):
    """Server-side session authentication for admins.

    Inherits DRF's CSRF enforcement for authenticated unsafe requests. The only change is that an
    unauthenticated request yields 401 (not 403), so clients can tell "log in" from "not allowed".
    JWT cookies are never looked at here.
    """

    def authenticate_header(self, request):
        return "Session"
