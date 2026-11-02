from django.contrib.auth import authenticate, get_user, login, logout
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import IsAdminRole
from accounts.serializers import LoginSerializer, UserSummarySerializer
from audit.models import AuditEvent
from audit.serializers import AuditEventSerializer
from audit.services import record_event, record_failed_admin_login
from config.api import CsrfProtectedAPIView
from profiles.models import HealthProfile
from profiles.serializers import AdminProfileDetailSerializer, AdminProfileListSerializer

from .authentication import AdminSessionAuthentication


class AdminLoginView(CsrfProtectedAPIView):
    """Credentials -> server-side session (Set-Cookie: HttpOnly session id).

    Nothing identifying the admin is ever handed to JavaScript, so there is nothing for the
    frontend to "edit" to impersonate an admin: authority lives in the server-side session row.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        request=LoginSerializer,
        responses={200: UserSummarySerializer, 401: OpenApiResponse(description="Invalid credentials")},
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        creds = serializer.validated_data

        user = authenticate(request=request, username=creds["email"], password=creds["password"])
        if user is None or user.role != User.Role.ADMIN:
            record_failed_admin_login(request, creds["email"])
            raise AuthenticationFailed("Invalid email or password.", code="invalid_credentials")

        login(request, user)  # rotates the session key (anti-fixation) and the CSRF token
        record_event(request, AuditEvent.Action.ADMIN_LOGIN, actor=user)
        return Response({"user": UserSummarySerializer(user).data})


class AdminLogoutView(CsrfProtectedAPIView):
    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={200: OpenApiResponse(description="Session destroyed")})
    def post(self, request):
        # This view has no authenticator (logout must work with an expired session), so look the
        # session user up directly to attribute the event.
        session_user = get_user(request._request)
        if getattr(session_user, "role", None) == User.Role.ADMIN:
            record_event(request, AuditEvent.Action.ADMIN_LOGOUT, actor=session_user)
        logout(request)  # deletes the server-side session row and the cookie
        return Response({"detail": "Logged out."})


class AdminMeView(APIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: UserSummarySerializer, 401: OpenApiResponse(description="Not signed in")})
    def get(self, request):
        return Response({"user": UserSummarySerializer(request.user).data})


class AdminPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50


class AdminProfileListView(generics.ListAPIView):
    """List/search/filter user profiles. Read-only."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [IsAdminRole]
    serializer_class = AdminProfileListSerializer
    pagination_class = AdminPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["full_name", "user__email"]
    ordering_fields = ["created_at", "full_name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        queryset = HealthProfile.objects.select_related("user")
        status_value = self.request.query_params.get("status")
        if status_value:
            if status_value not in HealthProfile.Status.values:
                raise ValidationError({"status": [f"Must be one of: {', '.join(HealthProfile.Status.values)}."]})
            queryset = queryset.filter(status=status_value)
        completion = self.request.query_params.get("completion")
        if completion:
            choices = HealthProfile.CompletionStatus.values
            if completion not in choices:
                raise ValidationError({"completion": [f"Must be one of: {', '.join(choices)}."]})
            queryset = queryset.filter(completion_status=completion)
        return queryset

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        # Tie-breaker so pagination is stable when many rows share a created_at / name.
        return queryset.order_by(*queryset.query.order_by, "-id")

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Matches full name or email (case-insensitive contains)."),
            OpenApiParameter("status", str, enum=HealthProfile.Status.values),
            OpenApiParameter("completion", str, enum=HealthProfile.CompletionStatus.values),
            OpenApiParameter("ordering", str, enum=["created_at", "-created_at", "full_name", "-full_name"]),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class AdminProfileDetailView(generics.RetrieveAPIView):
    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [IsAdminRole]
    serializer_class = AdminProfileDetailSerializer
    queryset = HealthProfile.objects.select_related("user")

    def retrieve(self, request, *args, **kwargs):
        profile = self.get_object()
        # Reading someone's profile is itself an action worth recording.
        record_event(request, AuditEvent.Action.ADMIN_PROFILE_VIEWED, profile=profile)
        return Response(self.get_serializer(profile).data)


class _ProfileStatusView(APIView):
    """Shared logic for activate / deactivate. Admin-only, CSRF-protected via the session auth."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [IsAdminRole]
    deactivate = True

    @extend_schema(request=None, responses={200: AdminProfileDetailSerializer})
    def post(self, request, pk):
        profile = get_object_or_404(HealthProfile.objects.select_related("user"), pk=pk)
        with transaction.atomic():
            if self.deactivate:
                profile.status = HealthProfile.Status.DEACTIVATED
                profile.deactivated_at = timezone.now()
            else:
                profile.status = HealthProfile.Status.ACTIVE
                profile.deactivated_at = None
            profile.save(update_fields=["status", "deactivated_at", "updated_at"])
            # is_active=False blocks login AND invalidates any live JWT: the access cookie is
            # re-checked against the DB on every request.
            profile.user.is_active = not self.deactivate
            profile.user.save(update_fields=["is_active"])
            action = (
                AuditEvent.Action.ADMIN_PROFILE_DEACTIVATED
                if self.deactivate
                else AuditEvent.Action.ADMIN_PROFILE_ACTIVATED
            )
            record_event(request, action, profile=profile, changed_fields=["status"])
        return Response(AdminProfileDetailSerializer(profile).data)


class AdminProfileDeactivateView(_ProfileStatusView):
    deactivate = True


class AdminProfileActivateView(_ProfileStatusView):
    deactivate = False


class AdminAuditEventListView(generics.ListAPIView):
    """Read-only audit trail, newest first. Filter by ``action`` and/or ``profile`` id."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [IsAdminRole]
    serializer_class = AuditEventSerializer
    pagination_class = AdminPagination

    def get_queryset(self):
        # Deletion markers come from EXISTS subqueries, not joins: joining the profile would drop events
        # of deleted profiles when filtering by profile, and would read profile contents for no reason.
        queryset = AuditEvent.objects.select_related("actor").annotate(
            profile_exists=Exists(HealthProfile.objects.filter(pk=OuterRef("profile_id"))),
            actor_exists=Exists(User.objects.filter(pk=OuterRef("actor_id"))),
        )
        params = self.request.query_params
        action = params.get("action")
        if action:
            if action not in AuditEvent.Action.values:
                raise ValidationError({"action": [f"Must be one of: {', '.join(AuditEvent.Action.values)}."]})
            queryset = queryset.filter(action=action)
        profile_id = params.get("profile")
        if profile_id:
            if not profile_id.isdigit():
                raise ValidationError({"profile": ["Must be a profile id."]})
            queryset = queryset.filter(profile_id=int(profile_id))
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("action", str, enum=AuditEvent.Action.values),
            OpenApiParameter("profile", int, description="Only events for this profile id."),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
