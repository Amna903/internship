"""Assistant API (admin only): status, the question endpoint, and policy documents with their versions
(upload, list, update, approve, reject, retire). Every write is audited with ids and version numbers only."""

import logging

from django.conf import settings
from django.db import IntegrityError
from django.utils.dateparse import parse_date
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
from .documents import (DocumentError, add_version, approve_version, create_document, pending_version, reject_version,
                        retire)
from .llm import LLMError, get_llm
from .service import QuestionInvalid
from .models import POLICY_AREAS, AnswerRecord, DocumentVersion, PolicyDocument
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


def version_json(v: DocumentVersion) -> dict:
    return {"number": v.number, "status": v.status, "sha256": v.sha256, "effective_date": v.effective_date,
            "created_at": v.created_at, "decided_at": v.decided_at, "chunks": v.chunks.count()}


def document_json(d: PolicyDocument) -> dict:
    # The content is not returned: an uploaded document is untrusted and is shown nowhere until approved.
    current, pending = d.current_version, pending_version(d)
    shown = current or pending
    return {"id": d.id, "filename": d.filename, "policy_area": d.policy_area, "status": d.status, "source": d.source,
            "sha256": shown.sha256 if shown else None,
            "current_version": current.number if current else None,
            "pending_version": pending.number if pending else None,
            "created_at": d.created_at, "approved_at": d.approved_at, "retired_at": d.retired_at,
            "chunks": d.chunks.count()}


def _read_upload(request):
    """The file plus its metadata, validated. Returns (valid, area, effective_date) or an error Response."""
    upload = request.FILES.get("file")
    if upload is not None and upload.size > MAX_UPLOAD_BYTES:
        return rejection(f"The file is larger than {MAX_UPLOAD_BYTES // 1000} KB.", "file_too_large",
                         status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    extra = set(request.data) - {"file", "policy_area", "effective_date"}
    if extra:
        return rejection("Unknown fields: " + ", ".join(sorted(extra)) + ".", "upload_rejected")
    area = request.data.get("policy_area") or "other"  # optional, so Week 4's /v1 upload contract still works
    if area not in POLICY_AREAS:
        return rejection("policy_area must be one of: " + ", ".join(POLICY_AREAS) + ".", "upload_rejected")
    raw_date = request.data.get("effective_date") or None
    effective = parse_date(raw_date) if raw_date else None
    if raw_date and effective is None:
        return rejection("effective_date must be a date in the form YYYY-MM-DD.", "upload_rejected")
    try:
        valid = validate_upload(upload.name if upload else None, upload.read(MAX_UPLOAD_BYTES + 1) if upload else None)
    except UploadRejected as exc:
        return rejection(str(exc), "upload_rejected")
    return valid, area, effective


def audit_detail(document_id: int, version: int) -> str:
    """Ids and version numbers only, never content. Version 1 keeps Week 4's form, like passage IDs."""
    return f"document:{document_id}" if version == 1 else f"document:{document_id}:v{version}"


def _refused(exc: DocumentError) -> Response:
    http = {"duplicate_document": status.HTTP_409_CONFLICT, "version_pending": status.HTTP_409_CONFLICT,
            "not_pending": status.HTTP_409_CONFLICT, "already_retired": status.HTTP_409_CONFLICT}.get(exc.code, 400)
    return rejection(str(exc), exc.code, http)


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
        read = _read_upload(request)
        if isinstance(read, Response):
            return read
        valid, area, effective = read
        try:
            document = create_document(valid.filename, valid.content, valid.sha256, PolicyDocument.Source.UPLOAD,
                                       request.user, policy_area=area, effective_date=effective)
        except DocumentError as exc:
            return _refused(exc)
        except IntegrityError:
            return rejection("A document with exactly this content already exists.", "duplicate_document",
                             status.HTTP_409_CONFLICT)
        record_event(request, AuditEvent.Action.ADMIN_DOCUMENT_UPLOADED, detail=audit_detail(document.id, 1))
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
        version = pending_version(document)
        if version is None:
            if document.status == PolicyDocument.Status.APPROVED:
                return rejection("This document is already approved.", "already_approved", status.HTTP_409_CONFLICT)
            return rejection("This document has no version waiting for approval.", "not_pending", status.HTTP_409_CONFLICT)
        return _approve(request, version)


def _approve(request, version: DocumentVersion) -> Response:
    try:
        approval = approve_version(version, request.user, get_embedder())
    except DocumentError as exc:
        return _refused(exc)
    except LLMError as exc:
        logger.error("assistant: indexing failed for document %s v%s (%s)", version.document_id, version.number, exc.reason)
        raise EmbeddingUnavailable() from None
    was = f":from_v{approval.previous}" if approval.previous else ""
    record_event(request, AuditEvent.Action.ADMIN_DOCUMENT_APPROVED,
                 detail=audit_detail(version.document_id, version.number) + was)
    return Response(document_json(PolicyDocument.objects.get(pk=version.document_id)))


def _version(document_id: int, number: int) -> DocumentVersion | None:
    return DocumentVersion.objects.filter(document_id=document_id, number=number).select_related("document").first()


class DocumentVersionsView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"
    parser_classes = [MultiPartParser]

    @extend_schema(summary="A document's version history (newest last)",
                   responses={200: OpenApiResponse(description="Versions"), 404: OpenApiResponse(description="No such document")})
    def get(self, request, document_id: int):
        document = PolicyDocument.objects.filter(id=document_id).first()
        if document is None:
            return rejection("No such document.", "not_found", status.HTTP_404_NOT_FOUND)
        return Response({"document": document_json(document), "versions": [version_json(v) for v in document.versions.all()]})

    @extend_schema(summary="Upload a new version of a document. It stays pending; the current version stays searchable.",
                   responses={201: OpenApiResponse(description="New pending version"), 400: OpenApiResponse(description="Rejected file"),
                              404: OpenApiResponse(description="No such document"),
                              409: OpenApiResponse(description="Identical to the current version, or a version is already pending"),
                              413: OpenApiResponse(description="File too large")})
    def post(self, request, document_id: int):
        document = PolicyDocument.objects.filter(id=document_id).first()
        if document is None:
            return rejection("No such document.", "not_found", status.HTTP_404_NOT_FOUND)
        read = _read_upload(request)
        if isinstance(read, Response):
            return read
        valid, area, effective = read
        if "policy_area" in request.data:
            return rejection("A version can't change the document's policy area.", "upload_rejected")
        try:
            version = add_version(document, valid.content, valid.sha256, request.user, effective_date=effective)
        except DocumentError as exc:
            return _refused(exc)
        record_event(request, AuditEvent.Action.ADMIN_DOCUMENT_VERSION_UPLOADED,
                     detail=audit_detail(document.id, version.number))
        return Response(version_json(version), status=status.HTTP_201_CREATED)


class DocumentVersionApproveView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(summary="Approve a pending version: index it, then swap it in atomically",
                   responses={200: OpenApiResponse(description="Approved and searchable"), 404: OpenApiResponse(description="No such version"),
                              409: OpenApiResponse(description="Not pending"),
                              503: OpenApiResponse(description="Indexing unavailable; nothing changed")})
    def post(self, request, document_id: int, number: int):
        version = _version(document_id, number)
        if version is None:
            return rejection("No such version.", "not_found", status.HTTP_404_NOT_FOUND)
        return _approve(request, version)


class DocumentVersionRejectView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(summary="Reject a pending version. It is kept, never indexed.",
                   responses={200: OpenApiResponse(description="Rejected"), 404: OpenApiResponse(description="No such version"),
                              409: OpenApiResponse(description="Not pending")})
    def post(self, request, document_id: int, number: int):
        version = _version(document_id, number)
        if version is None:
            return rejection("No such version.", "not_found", status.HTTP_404_NOT_FOUND)
        try:
            version = reject_version(version, request.user)
        except DocumentError as exc:
            return _refused(exc)
        record_event(request, AuditEvent.Action.ADMIN_DOCUMENT_VERSION_REJECTED,
                     detail=audit_detail(document_id, number))
        return Response(version_json(version))


class DocumentRetireView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(summary="Retire a document: remove it from search, keep every version for audit",
                   responses={200: OpenApiResponse(description="Retired"), 404: OpenApiResponse(description="No such document"),
                              409: OpenApiResponse(description="Already retired")})
    def post(self, request, document_id: int):
        document = PolicyDocument.objects.filter(id=document_id).first()
        if document is None:
            return rejection("No such document.", "not_found", status.HTTP_404_NOT_FOUND)
        try:
            document = retire(document, request.user)
        except DocumentError as exc:
            return _refused(exc)
        record_event(request, AuditEvent.Action.ADMIN_DOCUMENT_RETIRED, detail=f"document:{document.id}")
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
        event = record_event(request, AuditEvent.Action.ADMIN_ASSISTANT_ASKED, detail=f"{result.status}:{question_length}")
        by_id = {s["passage_id"]: s for s in answered.sources}
        citations = [{**c, "source": by_id[c["passage_id"]]["source"], "document_id": by_id[c["passage_id"]]["document_id"],
                      "version": by_id[c["passage_id"]]["version"]} for c in result.citations]
        edition = ("passage_id", "document_id", "version", "sha256")
        # Which editions the answer used, so the audit can always tell. Never the question or answer text.
        AnswerRecord.objects.create(
            audit_event=event, status=result.status, public_reason=answered.public_reason or "", model=result.model,
            citations=[{k: by_id[c["passage_id"]][k] for k in edition} for c in result.citations],
            sources=[{k: s[k] for k in edition} for s in answered.sources])
        if result.status in ERRORS:
            raise AssistantError(*ERRORS[result.status])
        return Response({
            "status": result.status,
            "answer": result.answer,
            "citations": citations,
            "sources": answered.sources,
            "reason": answered.public_reason,
            "stale_chunks_skipped": answered.stale_skipped,
            "usage": result.usage,
            "model": result.model,
            "model_called": result.model_called,
            "settings": answered.settings,
            "disclaimer": DISCLAIMER,
        })

