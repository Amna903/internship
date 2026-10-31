from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import CookieJWTAuthentication
from accounts.permissions import IsStandardUser
from audit.models import AuditEvent
from audit.services import record_event
from config.exceptions import Conflict

from .models import HealthProfile
from .serializers import HealthProfileSerializer


# Fields whose changes are audited (by name only, never by value).
TRACKED_FIELDS = [
    name for name in HealthProfileSerializer.Meta.fields
    if name not in HealthProfileSerializer.Meta.read_only_fields and name != "email"
]


class MeProfileView(APIView):
    """The signed-in user's own profile.

    There is deliberately no ``/profiles/<id>`` route for standard users: the profile is always
    resolved from ``request.user``, so one user can never address another user's data.
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsStandardUser]

    def _profile(self, request) -> HealthProfile:
        try:
            return request.user.profile
        except ObjectDoesNotExist:
            raise NotFound("Profile not found.", code="profile_not_found")

    @extend_schema(responses={200: HealthProfileSerializer, 404: OpenApiResponse(description="No profile yet")})
    def get(self, request):
        return Response(HealthProfileSerializer(self._profile(request)).data)

    @extend_schema(
        request=HealthProfileSerializer,
        responses={200: HealthProfileSerializer, 400: OpenApiResponse(description="Validation error")},
    )
    def patch(self, request):
        profile = self._profile(request)
        serializer = HealthProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        before = {name: getattr(profile, name) for name in TRACKED_FIELDS}
        with transaction.atomic():
            serializer.save()
            changed = [name for name in TRACKED_FIELDS if getattr(profile, name) != before[name]]
            if changed:  # a no-op save is not an edit
                record_event(request, AuditEvent.Action.PROFILE_UPDATED, profile=profile, changed_fields=changed)
        return Response(serializer.data)

    @extend_schema(
        request=None,
        responses={204: OpenApiResponse(description="Profile deleted"), 404: OpenApiResponse(description="No profile")},
    )
    def delete(self, request):
        """Delete the caller's own profile. The account stays (they can sign in and create a new profile);
        the audit trail keeps a ``profile.deleted`` row with no profile data in it."""
        profile = self._profile(request)
        with transaction.atomic():
            # Recorded before the delete so the event can be written; the FK is then nulled (SET_NULL).
            record_event(request, AuditEvent.Action.PROFILE_DELETED, profile=profile)
            profile.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        request=HealthProfileSerializer,
        responses={201: HealthProfileSerializer, 409: OpenApiResponse(description="Profile already exists")},
    )
    def post(self, request):
        """Create the profile if the account has none (signup normally creates it)."""
        if HealthProfile.objects.filter(user=request.user).exists():
            raise Conflict("A profile already exists for this account. Use PATCH to update it.")
        serializer = HealthProfileSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            profile = serializer.save(user=request.user)
            record_event(request, AuditEvent.Action.PROFILE_CREATED, profile=profile)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
