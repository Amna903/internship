"""Assistant API (admin only). Step 9: the status endpoint; the question endpoint arrives in Step 11."""

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from predictions.views import AdminOnlyAPIView

from .costs import ILLUSTRATIVE_HOSTED_PER_1K
from .prompts import CHARS_PER_TOKEN, SAFETY_MARGIN
from .schema import ANSWER_SCHEMA, MAX_ANSWER_CHARS, MAX_CITATIONS
from .service import MAX_QUESTION_CHARS


class AssistantStatusView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(summary="Assistant configuration: model, generation settings, context strategy, output schema",
                   responses={200: OpenApiResponse(description="Configuration"),
                              401: OpenApiResponse(description="Not signed in as admin"),
                              403: OpenApiResponse(description="Not an admin")})
    def get(self, request):
        cfg = settings.ASSISTANT
        # No call to the model here, and no server address in the response.
        return Response({
            "provider": "local (Ollama)" if cfg["PROVIDER"] == "ollama" else cfg["PROVIDER"],
            "model": cfg["MODEL"],
            "temperature": cfg["TEMPERATURE"],
            "max_output_tokens": cfg["MAX_OUTPUT_TOKENS"],
            "context_tokens": cfg["CONTEXT_TOKENS"],
            "timeout_seconds": cfg["TIMEOUT_SECONDS"],
            "context_strategy": (f"System prompt and question always included; ranked passages fill the rest, lowest "
                                 f"ranked dropped first. Token counts are approximate ({CHARS_PER_TOKEN} characters "
                                 f"per token) with a {int(SAFETY_MARGIN * 100)}% safety margin."),
            "limits": {"question_chars": MAX_QUESTION_CHARS, "answer_chars": MAX_ANSWER_CHARS,
                       "citations": MAX_CITATIONS},
            "output_schema": ANSWER_SCHEMA,
            "cost": {"local_usd_per_call": 0.0, "illustrative_hosted_usd_per_1k_tokens": ILLUSTRATIVE_HOSTED_PER_1K},
            "data_policy": "Only approved fictional clinic policies and the question reach the model; obvious "
                           "identifiers in questions are redacted first. The model runs locally.",
        })
