import logging

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import IsAdminRole
from adminpanel.authentication import AdminSessionAuthentication
from audit.models import AuditEvent
from audit.services import record_event
from config.exceptions import error_response
from ml import inference

from .serializers import NoShowRequestSerializer, NoShowResponseSerializer

logger = logging.getLogger(__name__)


def _model_or_503():
    try:
        return inference.load(str(settings.ML_ARTIFACT_DIR)), None
    except inference.ModelUnavailable as exc:
        logger.error("no-show model unavailable: %s", exc)  # detail goes to the log, not the client
        return None, error_response(
            "model_unavailable", "The prediction model is not available right now.", status.HTTP_503_SERVICE_UNAVAILABLE
        )


class NoShowPredictView(APIView):
    """Estimate the chance that a (synthetic) appointment is missed. Admin-only, v1."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [IsAdminRole]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "predict"

    @extend_schema(
        request=NoShowRequestSerializer,
        responses={
            200: NoShowResponseSerializer,
            400: OpenApiResponse(description="Malformed or out-of-range input"),
            503: OpenApiResponse(description="Model unavailable"),
        },
    )
    def post(self, request):
        serializer = NoShowRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        model, failure = _model_or_503()
        if failure:
            return failure
        result = inference.predict(model, serializer.validated_data)
        # Who asked and when, never the inputs or the score.
        record_event(request, AuditEvent.Action.ADMIN_PREDICTION)
        return Response({"model_version": model.version, "prediction": result, "disclaimer": inference.DISCLAIMER})


class NoShowModelInfoView(APIView):
    """Model card: version, metrics, threshold and input schema of the model being served."""

    authentication_classes = [AdminSessionAuthentication]
    permission_classes = [IsAdminRole]

    @extend_schema(responses={200: OpenApiResponse(description="Model card"), 503: OpenApiResponse(description="Model unavailable")})
    def get(self, request):
        model, failure = _model_or_503()
        if failure:
            return failure
        m = model.metadata
        selected = m["selected_model"]
        return Response({
            "model_version": model.version,
            "selected_model": selected,
            "task": m["task"],
            "decision_threshold": m["decision_threshold"],
            "train_no_show_rate": m["train_no_show_rate"],
            "test_metrics": m["test_metrics"],  # every candidate, so the comparison is visible
            "data": m["data"],
            "features": m["features"],
            "disclaimer": inference.DISCLAIMER,
        })
