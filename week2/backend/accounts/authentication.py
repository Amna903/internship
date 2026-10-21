from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import CSRFCheck
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import RevokedAccessToken


class CookieJWTAuthentication(JWTAuthentication):
    """Authenticate standard users from the HttpOnly access-token cookie.

    * Only the cookie is read. The ``Authorization`` header is deliberately ignored, so there is
      exactly one place a token can come from.
    * Because browsers attach cookies automatically, unsafe methods (POST/PATCH/...) must also
      carry a valid CSRF token - same rule DRF applies to ``SessionAuthentication``.
    * Access tokens revoked by logout are rejected (RevokedAccessToken), so logout is immediate.
    * Admin sessions are never consulted here: this class knows nothing about Django sessions.
    """

    def authenticate(self, request):
        raw_token = request.COOKIES.get(settings.JWT_ACCESS_COOKIE)
        if not raw_token:
            return None

        validated_token = self.get_validated_token(raw_token)  # signature, expiry, token type
        if RevokedAccessToken.objects.filter(jti=validated_token["jti"]).exists():
            raise exceptions.AuthenticationFailed("Session has been signed out.", code="token_revoked")
        user = self.get_user(validated_token)
        if not user.is_active:
            raise exceptions.AuthenticationFailed("Account is disabled.", code="user_inactive")

        self._enforce_csrf(request)
        return user, validated_token

    @staticmethod
    def _enforce_csrf(request):
        check = CSRFCheck(lambda req: None)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise exceptions.PermissionDenied(f"CSRF Failed: {reason}", code="csrf_failed")
