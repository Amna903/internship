from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class CookieJWTScheme(OpenApiAuthenticationExtension):
    target_class = "accounts.authentication.CookieJWTAuthentication"
    name = "userJwtCookie"

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.JWT_ACCESS_COOKIE,
            "description": "Short-lived JWT access token, set as an HttpOnly cookie by POST /api/auth/user/login.",
        }
