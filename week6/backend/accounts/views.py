import datetime

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import update_last_login
from django.db import IntegrityError, transaction
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from audit.models import AuditEvent
from audit.services import record_event
from config.api import CsrfProtectedAPIView
from config.exceptions import error_response

from .cookies import access_lifetime_seconds, clear_auth_cookies, set_auth_cookies
from .models import RevokedAccessToken, User
from .serializers import LoginSerializer, SignupSerializer, UserSummarySerializer
from .services import register_user


class SessionInfoSerializer(serializers.Serializer):
    user = UserSummarySerializer()
    access_expires_in = serializers.IntegerField(help_text="Seconds until the access cookie expires.")


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfTokenView(APIView):
    """Sets the ``csrftoken`` cookie. Call once on app start-up and after login/logout."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: OpenApiResponse(description="CSRF cookie set; token also returned.")})
    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class SignupView(CsrfProtectedAPIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "signup"

    @extend_schema(
        request=SignupSerializer,
        responses={201: UserSummarySerializer, 400: OpenApiResponse(description="Validation error")},
    )
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                user = register_user(**serializer.validated_data)
                record_event(request, AuditEvent.Action.PROFILE_CREATED, actor=user, profile=user.profile)
        except IntegrityError:  # lost a race with a concurrent signup for the same email
            raise ValidationError({"email": ["An account with this email already exists."]})
        return Response({"user": UserSummarySerializer(user).data}, status=status.HTTP_201_CREATED)


class UserLoginView(CsrfProtectedAPIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        request=LoginSerializer,
        responses={200: SessionInfoSerializer, 401: OpenApiResponse(description="Invalid credentials")},
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        creds = serializer.validated_data

        user = authenticate(request=request, username=creds["email"], password=creds["password"])
        # Same error for unknown email, wrong password, deactivated account and admin accounts:
        # the endpoint must not reveal which accounts exist or which role they have.
        if user is None or user.role != User.Role.USER:
            raise AuthenticationFailed("Invalid email or password.", code="invalid_credentials")

        update_last_login(None, user)
        refresh = RefreshToken.for_user(user)
        response = Response({"user": UserSummarySerializer(user).data, "access_expires_in": access_lifetime_seconds()})
        set_auth_cookies(response, refresh.access_token, refresh)
        return response


class UserRefreshView(CsrfProtectedAPIView):
    """Rotate the refresh token and issue a new access token (both set as cookies)."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        request=None, responses={200: SessionInfoSerializer, 401: OpenApiResponse(description="Not signed in")}
    )
    def post(self, request):
        raw = request.COOKIES.get(settings.JWT_REFRESH_COOKIE)
        if not raw:
            return error_response("refresh_missing", "No refresh token.", status.HTTP_401_UNAUTHORIZED)

        try:
            old = RefreshToken(raw)  # checks signature, expiry and the blacklist
            user = User.objects.filter(pk=old["user_id"], is_active=True, role=User.Role.USER).first()
            if user is None:
                raise TokenError("User is not allowed to refresh.")
            with transaction.atomic():
                old.blacklist()  # one-time use: a replayed refresh token is rejected
                new_refresh = RefreshToken.for_user(user)
        except TokenError:
            response = error_response(
                "token_not_valid", "Session expired. Please sign in again.", status.HTTP_401_UNAUTHORIZED
            )
            clear_auth_cookies(response)
            return response

        response = Response({"user": UserSummarySerializer(user).data, "access_expires_in": access_lifetime_seconds()})
        set_auth_cookies(response, new_refresh.access_token, new_refresh)
        return response


class UserLogoutView(CsrfProtectedAPIView):
    """Revoke this browser's tokens and clear both cookies. Idempotent.

    Revokes: the refresh token (blacklisted) and the current access token (denylisted until it would
    have expired). Does not touch the member's other signed-in browsers or devices.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={200: OpenApiResponse(description="Logged out")})
    def post(self, request):
        raw = request.COOKIES.get(settings.JWT_REFRESH_COOKIE)
        if raw:
            try:
                RefreshToken(raw).blacklist()
            except TokenError:
                pass  # already expired / blacklisted: nothing left to revoke
        raw_access = request.COOKIES.get(settings.JWT_ACCESS_COOKIE)
        if raw_access:
            try:
                access = AccessToken(raw_access)
            except TokenError:
                pass  # expired or invalid: it already authenticates nothing
            else:
                expires_at = datetime.datetime.fromtimestamp(access["exp"], tz=datetime.timezone.utc)
                RevokedAccessToken.objects.get_or_create(jti=access["jti"], defaults={"expires_at": expires_at})
        RevokedAccessToken.objects.filter(expires_at__lt=timezone.now()).delete()
        response = Response({"detail": "Logged out."})
        clear_auth_cookies(response)
        return response
