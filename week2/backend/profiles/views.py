from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import CookieJWTAuthentication
from accounts.permissions import IsStandardUser
from config.exceptions import Conflict

from .models import HealthProfile
from .serializers import HealthProfileSerializer


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
        serializer = HealthProfileSerializer(self._profile(request), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

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
        serializer.save(user=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
