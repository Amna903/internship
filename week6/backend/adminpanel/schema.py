from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class AdminSessionScheme(OpenApiAuthenticationExtension):
    target_class = "adminpanel.authentication.AdminSessionAuthentication"
    name = "adminSession"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.SESSION_COOKIE_NAME,
            "description": "Server-side session cookie, set by POST /api/admin/login.",
        }
