"""Assistant API (admin only): status, policy documents (upload, list, approve). The question endpoint
arrives in Step 11."""

import logging

from django.conf import settings
from django.db import IntegrityError
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from audit.models import AuditEvent
from audit.services import record_event
from predictions.views import AdminOnlyAPIView

from predictions.views import SmallJSONParser

from .answering import answer_question
from .embeddings import get_embedder
from .indexing import approve
from .llm import LLMError, get_llm
from .service import QuestionInvalid
from .models import PolicyDocument
from .uploads import MAX_UPLOAD_BYTES, UploadRejected, validate_upload

logger = logging.getLogger(__name__)

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
            "embedder": cfg["EMBED_MODEL"] if cfg["EMBEDDER"] == "ollama" else cfg["EMBEDDER"],
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


class EmbeddingUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "The document could not be indexed right now; it stays pending. Try again later."
    default_code = "embedding_unavailable"


def document_json(d: PolicyDocument) -> dict:
    # The content is not returned in lists: an uploaded document is untrusted and is shown nowhere until approved.
    return {"id": d.id, "filename": d.filename, "status": d.status, "source": d.source, "sha256": d.sha256,
            "created_at": d.created_at, "approved_at": d.approved_at, "chunks": d.chunks.count()}


def rejection(message: str, code: str, http=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=http)


class DocumentsView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"
    parser_classes = [MultiPartParser]

    @extend_schema(summary="List policy documents (pending and approved)",
                   responses={200: OpenApiResponse(description="Documents")})
    def get(self, request):
        return Response({"documents": [document_json(d) for d in PolicyDocument.objects.all()]})

    @extend_schema(summary="Upload a policy document (.txt or .md, UTF-8, at most 50 KB). It stays pending until approved.",
                   responses={201: OpenApiResponse(description="Uploaded, pending approval"),
                              400: OpenApiResponse(description="Rejected file"),
                              409: OpenApiResponse(description="Same content already uploaded"),
                              413: OpenApiResponse(description="File too large")})
    def post(self, request):
        upload = request.FILES.get("file")
        if upload is not None and upload.size > MAX_UPLOAD_BYTES:
            return rejection(f"The file is larger than {MAX_UPLOAD_BYTES // 1000} KB.", "file_too_large",
                             status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        try:
            valid = validate_upload(upload.name if upload else None, upload.read(MAX_UPLOAD_BYTES + 1) if upload else None)
        except UploadRejected as exc:
            return rejection(str(exc), "upload_rejected")
        if PolicyDocument.objects.filter(sha256=valid.sha256).exists():
            return rejection("A document with exactly this content already exists.", "duplicate_document",
                             status.HTTP_409_CONFLICT)
        try:
            document = PolicyDocument.objects.create(filename=valid.filename, sha256=valid.sha256, content=valid.content,
                                                     source=PolicyDocument.Source.UPLOAD, uploaded_by=request.user)
        except IntegrityError:
            return rejection("A document with exactly this content already exists.", "duplicate_document",
                             status.HTTP_409_CONFLICT)
        record_event(request, AuditEvent.Action.ADMIN_DOCUMENT_UPLOADED, detail=f"document:{document.id}")
        return Response(document_json(document), status=status.HTTP_201_CREATED)


class DocumentApproveView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(summary="Approve a pending document: index it and make it searchable",
                   responses={200: OpenApiResponse(description="Approved and indexed"),
                              404: OpenApiResponse(description="No such document"),
                              409: OpenApiResponse(description="Already approved"),
                              503: OpenApiResponse(description="Indexing unavailable; stays pending")})
    def post(self, request, document_id: int):
        document = PolicyDocument.objects.filter(id=document_id).first()
        if document is None:
            return rejection("No such document.", "not_found", status.HTTP_404_NOT_FOUND)
        if document.status == PolicyDocument.Status.APPROVED:
            return rejection("This document is already approved.", "already_approved", status.HTTP_409_CONFLICT)
        try:
            approve(document, request.user, get_embedder())
        except LLMError as exc:
            logger.error("assistant: indexing failed for document %s (%s)", document.id, exc.reason)
            raise EmbeddingUnavailable() from None
        record_event(request, AuditEvent.Action.ADMIN_DOCUMENT_APPROVED, detail=f"document:{document.id}")
        document.refresh_from_db()
        return Response(document_json(document))


DISCLAIMER = ("Educational assistant for a fictional clinic's policies. Answers come only from approved policy "
              "documents and are checked against them; it gives no medical advice.")


class AssistantError(APIException):
    def __init__(self, http_status: int, code: str, message: str):
        self.status_code = http_status
        super().__init__(detail=message, code=code)


ERRORS = {
    "timeout": (status.HTTP_504_GATEWAY_TIMEOUT, "assistant_timeout",
                "The assistant took too long to answer. Please try again."),
    "unavailable": (status.HTTP_503_SERVICE_UNAVAILABLE, "assistant_unavailable",
                    "The assistant is temporarily unavailable."),
    "invalid_output": (status.HTTP_502_BAD_GATEWAY, "assistant_invalid_output",
                       "The assistant could not produce a valid answer. Please try again."),
}


class AskView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"
    parser_classes = [SmallJSONParser]

    @extend_schema(
        summary="Ask the clinic-policy assistant a question",
        description=("Answers only from approved fictional policies, with citations the server has checked. "
                     "Status is decided by the server: answered, insufficient_information or refused."),
        responses={200: OpenApiResponse(description="answered, insufficient_information or refused"),
                   400: OpenApiResponse(description="Invalid question"), 401: OpenApiResponse(description="Not signed in"),
                   403: OpenApiResponse(description="Not an admin, or CSRF token missing"),
                   429: OpenApiResponse(description="Rate limit exceeded"),
                   502: OpenApiResponse(description="Model produced invalid output"),
                   503: OpenApiResponse(description="Model unavailable"), 504: OpenApiResponse(description="Model timeout")},
    )
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        if set(data) - {"question"}:
            return rejection("Only a 'question' field is accepted.", "invalid_request")
        try:
            answered = answer_question(data.get("question"), get_llm(), get_embedder())
        except QuestionInvalid as exc:
            return rejection(str(exc), "invalid_question")
        result = answered.result
        # Audit: who asked, the outcome and the question's length. Never the question text.
        question_length = len(data.get("question") or "")
        record_event(request, AuditEvent.Action.ADMIN_ASSISTANT_ASKED, detail=f"{result.status}:{question_length}")
        if result.status in ERRORS:
            raise AssistantError(*ERRORS[result.status])
        by_id = {s["passage_id"]: s["source"] for s in answered.sources}
        return Response({
            "status": result.status,
            "answer": result.answer,
            "citations": [{**c, "source": by_id.get(c["passage_id"], c["passage_id"].split("#")[0])}
                          for c in result.citations],
            "sources": answered.sources,
            "reason": answered.public_reason,
            "stale_chunks_skipped": answered.stale_skipped,
            "usage": result.usage,
            "model": result.model,
            "model_called": result.model_called,
            "settings": answered.settings,
            "disclaimer": DISCLAIMER,
        })

