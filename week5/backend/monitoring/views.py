from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from predictions.views import AdminOnlyAPIView

from .drift import summary


class MonitoringView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "predictions"

    @extend_schema(summary="Prediction monitoring: distribution against the baseline (PSI), latency, failure rate",
                   responses={200: OpenApiResponse(description="Summary"), 400: OpenApiResponse(description="Bad ?days")})
    def get(self, request):
        raw = request.query_params.get("days", "7")
        if not raw.isdigit() or not 1 <= int(raw) <= 90:
            return Response({"error": {"code": "invalid_filter", "message": "days must be a whole number from 1 to 90."}},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(summary(int(raw)))
