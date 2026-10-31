"""Versioned no-show estimate API (admin only).

/api/v1/ is the API contract; `model_version` in each response names the model behind the answer. A new
model with the same inputs keeps /v1/; changed inputs would need /v2/.
"""

import json
import logging

from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException, ParseError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from adminpanel.authentication import AdminSessionAuthentication
from audit.models import AuditEvent
from audit.services import record_event
from ml import config
from ml.inference import ModelUnavailable, get_model

from .serializers import NoShowInputSerializer, PredictionResponseSerializer

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 4096  # one appointment is ~300 bytes; anything far larger is not a valid request


class RequestTooLarge(APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = f"Request body is larger than {MAX_BODY_BYTES} bytes."
    default_code = "request_too_large"


class ModelUnavailableError(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The estimate service is temporarily unavailable."
    default_code = "model_unavailable"


class SmallJSONParser(JSONParser):
    """Reads at most MAX_BODY_BYTES + 1 bytes, so an oversized body is rejected without being parsed."""

    def parse(self, stream, media_type=None, parser_context=None):
        raw = stream.read(MAX_BODY_BYTES + 1) if stream is not None else b""
        if len(raw) > MAX_BODY_BYTES:
            raise RequestTooLarge()
        if not raw.strip():
            raise ParseError("Request body is empty.")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            raise ParseError("Request body is not valid JSON.") from None


def _model():
    try:
        return get_model()
    except ModelUnavailable as exc:
        # The reason (e.g. "SHA-256 does not match") goes to the server log only; clients get a generic 503.
        logger.error("no-show model unavailable: %s", exc.reason)
        raise ModelUnavailableError() from None


class AdminOnlyAPIView(APIView):
    """Week 2 rules for every ML endpoint: admin session (CSRF enforced on writes) and role check."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [IsAdminRole]


EXAMPLE_INPUT = {
    "lead_time_days": 14, "appointment_weekday": "tuesday", "appointment_hour": 10, "age_band": "35-44",
    "visit_type": "in_person", "booking_channel": "web", "reminder_sent": True,
    "prior_appointments": 4, "prior_no_shows": 0, "distance_km": 6.5,
}


class NoShowPredictionView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "predictions"
    parser_classes = [SmallJSONParser]

    @extend_schema(
        summary="Estimate whether a fictional appointment may be missed",
        description=("Educational, synthetic. The caller supplies the appointment history counts; the API "
                     "does not look them up. Returns a probability and a plain-language reminder suggestion."),
        request=NoShowInputSerializer,
        responses={
            200: PredictionResponseSerializer,
            400: OpenApiResponse(description="Invalid input (unknown field, wrong type, out of range, malformed JSON)"),
            401: OpenApiResponse(description="Not signed in as admin"),
            403: OpenApiResponse(description="Not an admin, or CSRF token missing"),
            413: OpenApiResponse(description="Body too large"),
            429: OpenApiResponse(description="Rate limit exceeded"),
            503: OpenApiResponse(description="Model unavailable"),
        },
        examples=[OpenApiExample("One appointment", value=EXAMPLE_INPUT, request_only=True)],
    )
    def post(self, request):
        serializer = NoShowInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        model = _model()
        prediction = model.predict([serializer.validated_data])[0]
        # Audit: who asked and which model answered. Never the input values.
        record_event(request, AuditEvent.Action.ADMIN_PREDICTION_MADE, detail=model.version)
        return Response({"model_version": model.version, "prediction": prediction, "disclaimer": config.DISCLAIMER})


class NoShowModelView(AdminOnlyAPIView):
    @extend_schema(summary="Model card for the served no-show model",
                   responses={200: OpenApiResponse(description="Model card"), 503: OpenApiResponse(description="Model unavailable")})
    def get(self, request):
        model = _model()
        meta = model.metadata
        return Response({
            "model_version": model.version,
            "task": meta["task"],
            "estimator": meta["estimator"],
            "disclaimer": meta["disclaimer"],
            "inputs": meta["features"],
            "inputs_note": "The caller supplies the appointment history counts; the API does not look them up.",
            "decision": meta["decision"],
            "metrics": meta["metrics"],
            "training_data": meta["training_data"],
            "seed": meta["seed"],
            "libraries": meta["libraries"],
            "artifact_sha256": meta["artifact_sha256"],
        })
