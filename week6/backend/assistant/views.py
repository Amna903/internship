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
from predictions.views import AdminOnlyAPIView, SmallJSONParser

from .answering import answer_question
from .costs import ILLUSTRATIVE_HOSTED_PER_1K
from .documents import DocumentError, add_version, create_document, pending_version, reject_version, retire
from .embeddings import get_embedder
from .history import CONVERSATION_TOKENS, MAX_TURNS, ConversationLimit, HistoryInvalid
from .history import dump as dump_history
from .history import load as load_history
from .jobs import QueueUnavailable, audit_detail, queue_approval
from .llm import get_llm
from .models import POLICY_AREAS, AnswerRecord, DocumentVersion, IndexJob, PolicyDocument
from .prompts import CHARS_PER_TOKEN, SAFETY_MARGIN
from .schema import ANSWER_SCHEMA, MAX_ANSWER_CHARS, MAX_CITATIONS
from .service import MAX_QUESTION_CHARS, QuestionInvalid
from .uploads import MAX_UPLOAD_BYTES, UploadRejected, validate_upload

logger = logging.getLogger(__name__)


class AssistantStatusView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(
        summary="Assistant configuration: model, generation settings, context strategy, output schema",
        responses={
            200: OpenApiResponse(description="Configuration"),
            401: OpenApiResponse(description="Not signed in as admin"),
            403: OpenApiResponse(description="Not an admin"),
        },
    )
    def get(self, request):
        cfg = settings.ASSISTANT
        # No call to the model here, and no server address in the response.
        return Response(
            {
                "provider": "local (Ollama)" if cfg["PROVIDER"] == "ollama" else cfg["PROVIDER"],
                "model": cfg["MODEL"],
                "embedder": cfg["EMBED_MODEL"] if cfg["EMBEDDER"] == "ollama" else cfg["EMBEDDER"],
                "temperature": cfg["TEMPERATURE"],
                "max_output_tokens": cfg["MAX_OUTPUT_TOKENS"],
                "context_tokens": cfg["CONTEXT_TOKENS"],
                "timeout_seconds": cfg["TIMEOUT_SECONDS"],
                "context_strategy": (
                    f"System prompt and question always included; ranked passages fill the rest, lowest "
                    f"ranked dropped first. Token counts are approximate ({CHARS_PER_TOKEN} characters "
                    f"per token) with a {int(SAFETY_MARGIN * 100)}% safety margin."
                ),
                "limits": {
                    "question_chars": MAX_QUESTION_CHARS,
                    "answer_chars": MAX_ANSWER_CHARS,
                    "citations": MAX_CITATIONS,
                },
                "output_schema": ANSWER_SCHEMA,
                "cost": {
                    "local_usd_per_call": 0.0,
                    "illustrative_hosted_usd_per_1k_tokens": ILLUSTRATIVE_HOSTED_PER_1K,
                },
                "data_policy": "Only approved fictional clinic policies and the question reach the model; obvious "
                "identifiers in questions are redacted first. The model runs locally.",
            }
        )


def version_json(v: DocumentVersion) -> dict:
    return {
        "number": v.number,
        "status": v.status,
        "sha256": v.sha256,
        "effective_date": v.effective_date,
        "created_at": v.created_at,
        "decided_at": v.decided_at,
        "chunks": v.chunks.count(),
    }


def document_json(d: PolicyDocument) -> dict:
    # The content is not returned: an uploaded document is untrusted and is shown nowhere until approved.
    current, pending = d.current_version, pending_version(d)
    shown = current or pending
    return {
        "id": d.id,
        "filename": d.filename,
        "policy_area": d.policy_area,
        "status": d.status,
        "source": d.source,
        "sha256": shown.sha256 if shown else None,
        "current_version": current.number if current else None,
        "pending_version": pending.number if pending else None,
        "created_at": d.created_at,
        "approved_at": d.approved_at,
        "retired_at": d.retired_at,
        "chunks": d.chunks.count(),
    }


def _read_upload(request):
    """The file plus its metadata, validated. Returns (valid, area, effective_date) or an error Response."""
    upload = request.FILES.get("file")
    if upload is not None and upload.size > MAX_UPLOAD_BYTES:
        return rejection(
            f"The file is larger than {MAX_UPLOAD_BYTES // 1000} KB.",
            "file_too_large",
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
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


def _refused(exc: DocumentError) -> Response:
    http = {
        "duplicate_document": status.HTTP_409_CONFLICT,
        "version_pending": status.HTTP_409_CONFLICT,
        "not_pending": status.HTTP_409_CONFLICT,
        "already_retired": status.HTTP_409_CONFLICT,
    }.get(exc.code, 400)
    return rejection(str(exc), exc.code, http)


def rejection(message: str, code: str, http=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"error": {"code": code, "message": message}}, status=http)


class DocumentsView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"
    parser_classes = [MultiPartParser]

    @extend_schema(
        summary="List policy documents (pending and approved)",
        responses={200: OpenApiResponse(description="Documents")},
    )
    def get(self, request):
        return Response({"documents": [document_json(d) for d in PolicyDocument.objects.all()]})

    @extend_schema(
        summary="Upload a policy document (.txt or .md, UTF-8, at most 50 KB). It stays pending until approved.",
        responses={
            201: OpenApiResponse(description="Uploaded, pending approval"),
            400: OpenApiResponse(description="Rejected file"),
            409: OpenApiResponse(description="Same content already uploaded"),
            413: OpenApiResponse(description="File too large"),
        },
    )
    def post(self, request):
        read = _read_upload(request)
        if isinstance(read, Response):
            return read
        valid, area, effective = read
        try:
            document = create_document(
                valid.filename,
                valid.content,
                valid.sha256,
                PolicyDocument.Source.UPLOAD,
                request.user,
                policy_area=area,
                effective_date=effective,
            )
        except DocumentError as exc:
            return _refused(exc)
        except IntegrityError:
            return rejection(
                "A document with exactly this content already exists.", "duplicate_document", status.HTTP_409_CONFLICT
            )
        record_event(request, AuditEvent.Action.ADMIN_DOCUMENT_UPLOADED, detail=audit_detail(document.id, 1))
        return Response(document_json(document), status=status.HTTP_201_CREATED)


class DocumentApproveView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(
        summary="Approve a pending document: queue a background job that indexes it and makes it searchable",
        responses={
            202: OpenApiResponse(description="Job queued (the document and the job)"),
            200: OpenApiResponse(description="A job for this version is already open; that job"),
            404: OpenApiResponse(description="No such document"),
            409: OpenApiResponse(description="Already approved"),
            503: OpenApiResponse(description="Indexing queue unavailable; nothing changed"),
        },
    )
    def post(self, request, document_id: int):
        document = PolicyDocument.objects.filter(id=document_id).first()
        if document is None:
            return rejection("No such document.", "not_found", status.HTTP_404_NOT_FOUND)
        version = pending_version(document)
        if version is None:
            if document.status == PolicyDocument.Status.APPROVED:
                return rejection("This document is already approved.", "already_approved", status.HTTP_409_CONFLICT)
            return rejection(
                "This document has no version waiting for approval.", "not_pending", status.HTTP_409_CONFLICT
            )
        return _approve(request, version)


def job_json(job: IndexJob) -> dict:
    return {
        "id": job.id,
        "document_id": job.version.document_id,
        "version": job.version.number,
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "error_code": job.error_code or None,
        "chunks": job.chunks,
        "requested_by": job.requested_by_id,
        "queued_at": job.queued_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }


def _approve(request, version: DocumentVersion) -> Response:
    """Queue the approval as a background job (Week 5 Step 10). 202 with the new job; 200 with the open job
    when one is already queued or running for this version."""
    try:
        job, created = queue_approval(version, request.user, getattr(request, "request_id", ""))
    except DocumentError as exc:
        return _refused(exc)
    except QueueUnavailable:
        return rejection(
            "The indexing queue is unavailable. Nothing changed; try again shortly.",
            "queue_unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    body = {**document_json(PolicyDocument.objects.get(pk=version.document_id)), "job": job_json(job)}
    return Response(body, status=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK)


class IndexJobsView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "jobs"

    @extend_schema(
        operation_id="v1_assistant_jobs_list",
        summary="Background indexing jobs, newest first (at most 50; optional ?status=)",
        responses={200: OpenApiResponse(description="Jobs"), 400: OpenApiResponse(description="Unknown status")},
    )
    def get(self, request):
        jobs = IndexJob.objects.select_related("version")
        wanted = request.query_params.get("status")
        if wanted is not None:
            if wanted not in IndexJob.Status.values:
                return rejection("Unknown job status.", "invalid_filter")
            jobs = jobs.filter(status=wanted)
        return Response({"jobs": [job_json(j) for j in jobs[:50]]})


class IndexJobView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "jobs"

    @extend_schema(
        summary="One background indexing job",
        responses={200: OpenApiResponse(description="The job"), 404: OpenApiResponse(description="No such job")},
    )
    def get(self, request, job_id: int):
        job = IndexJob.objects.select_related("version").filter(pk=job_id).first()
        if job is None:
            return rejection("No such job.", "not_found", status.HTTP_404_NOT_FOUND)
        return Response(job_json(job))


def _version(document_id: int, number: int) -> DocumentVersion | None:
    return DocumentVersion.objects.filter(document_id=document_id, number=number).select_related("document").first()


class DocumentVersionsView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"
    parser_classes = [MultiPartParser]

    @extend_schema(
        summary="A document's version history (newest last)",
        responses={200: OpenApiResponse(description="Versions"), 404: OpenApiResponse(description="No such document")},
    )
    def get(self, request, document_id: int):
        document = PolicyDocument.objects.filter(id=document_id).first()
        if document is None:
            return rejection("No such document.", "not_found", status.HTTP_404_NOT_FOUND)
        return Response(
            {"document": document_json(document), "versions": [version_json(v) for v in document.versions.all()]}
        )

    @extend_schema(
        summary="Upload a new version of a document. It stays pending; the current version stays searchable.",
        responses={
            201: OpenApiResponse(description="New pending version"),
            400: OpenApiResponse(description="Rejected file"),
            404: OpenApiResponse(description="No such document"),
            409: OpenApiResponse(description="Identical to the current version, or a version is already pending"),
            413: OpenApiResponse(description="File too large"),
        },
    )
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
        record_event(
            request, AuditEvent.Action.ADMIN_DOCUMENT_VERSION_UPLOADED, detail=audit_detail(document.id, version.number)
        )
        return Response(version_json(version), status=status.HTTP_201_CREATED)


class DocumentVersionApproveView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(
        summary="Approve a pending version: queue a background job that indexes it, then swaps it in atomically",
        responses={
            202: OpenApiResponse(description="Job queued (the document and the job)"),
            200: OpenApiResponse(description="A job for this version is already open; that job"),
            404: OpenApiResponse(description="No such version"),
            409: OpenApiResponse(description="Not pending"),
            503: OpenApiResponse(description="Indexing queue unavailable; nothing changed"),
        },
    )
    def post(self, request, document_id: int, number: int):
        version = _version(document_id, number)
        if version is None:
            return rejection("No such version.", "not_found", status.HTTP_404_NOT_FOUND)
        return _approve(request, version)


class DocumentVersionRejectView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(
        summary="Reject a pending version. It is kept, never indexed.",
        responses={
            200: OpenApiResponse(description="Rejected"),
            404: OpenApiResponse(description="No such version"),
            409: OpenApiResponse(description="Not pending"),
        },
    )
    def post(self, request, document_id: int, number: int):
        version = _version(document_id, number)
        if version is None:
            return rejection("No such version.", "not_found", status.HTTP_404_NOT_FOUND)
        try:
            version = reject_version(version, request.user)
        except DocumentError as exc:
            return _refused(exc)
        record_event(
            request, AuditEvent.Action.ADMIN_DOCUMENT_VERSION_REJECTED, detail=audit_detail(document_id, number)
        )
        return Response(version_json(version))


class DocumentRetireView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"

    @extend_schema(
        summary="Retire a document: remove it from search, keep every version for audit",
        responses={
            200: OpenApiResponse(description="Retired"),
            404: OpenApiResponse(description="No such document"),
            409: OpenApiResponse(description="Already retired"),
        },
    )
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


DISCLAIMER = (
    "Educational assistant for a fictional clinic's policies. Answers come only from approved policy "
    "documents and are checked against them; it gives no medical advice."
)


class AssistantError(APIException):
    def __init__(self, http_status: int, code: str, message: str):
        self.status_code = http_status
        super().__init__(detail=message, code=code)


ERRORS = {
    "timeout": (
        status.HTTP_504_GATEWAY_TIMEOUT,
        "assistant_timeout",
        "The assistant took too long to answer. Please try again.",
    ),
    "unavailable": (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "assistant_unavailable",
        "The assistant is temporarily unavailable.",
    ),
    "invalid_output": (
        status.HTTP_502_BAD_GATEWAY,
        "assistant_invalid_output",
        "The assistant could not produce a valid answer. Please try again.",
    ),
}


class AskJSONParser(SmallJSONParser):
    """Room for the question plus the signed conversation history (Week 5 Step 5)."""

    max_bytes = 32 * 1024


class AskView(AdminOnlyAPIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "assistant"
    parser_classes = [AskJSONParser]

    @extend_schema(
        summary="Ask the clinic-policy assistant a question",
        description=(
            "Answers only from approved fictional policies, with citations the server has checked. "
            "Status is decided by the server: answered, insufficient_information or refused. "
            "For a follow-up, send back the `history` from the previous answer (signed, tied to you, "
            "valid for 30 minutes); omit it to start a new conversation."
        ),
        responses={
            200: OpenApiResponse(description="answered, insufficient_information or refused"),
            400: OpenApiResponse(
                description="Invalid question, invalid or expired history, or the "
                "conversation limit reached (start a new conversation)"
            ),
            401: OpenApiResponse(description="Not signed in"),
            403: OpenApiResponse(description="Not an admin, or CSRF token missing"),
            413: OpenApiResponse(description="Request body too large"),
            429: OpenApiResponse(description="Rate limit exceeded"),
            502: OpenApiResponse(description="Model produced invalid output"),
            503: OpenApiResponse(description="Model unavailable"),
            504: OpenApiResponse(description="Model timeout"),
        },
    )
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        if set(data) - {"question", "area", "history"}:
            return rejection(
                "Only 'question', an optional 'area' and an optional 'history' are accepted.", "invalid_request"
            )
        area = data.get("area")
        if area is not None and area not in POLICY_AREAS:
            return rejection("area must be one of: " + ", ".join(POLICY_AREAS) + ".", "invalid_request")
        try:
            history = load_history(data.get("history"), request.user.id)
        except HistoryInvalid:
            return rejection("This conversation can't be continued. Start a new conversation.", "invalid_history")
        try:
            answered = answer_question(data.get("question"), get_llm(), get_embedder(), area=area, history=history)
        except QuestionInvalid as exc:
            return rejection(str(exc), "invalid_question")
        except ConversationLimit:
            return rejection(
                f"This conversation has reached its limit ({MAX_TURNS} questions or "
                f"{CONVERSATION_TOKENS:,} tokens). Start a new conversation.",
                "conversation_limit",
            )
        result = answered.result
        turn = history.turn_count + 1
        # Audit: who asked, the outcome and the question's length. Never the question text or the history.
        question_length = len(data.get("question") or "")
        event = record_event(
            request, AuditEvent.Action.ADMIN_ASSISTANT_ASKED, detail=f"{result.status}:{question_length}"
        )
        by_id = {s["passage_id"]: s for s in answered.sources}
        citations = [
            {
                **c,
                "source": by_id[c["passage_id"]]["source"],
                "document_id": by_id[c["passage_id"]]["document_id"],
                "version": by_id[c["passage_id"]]["version"],
            }
            for c in result.citations
        ]
        edition = ("passage_id", "document_id", "version", "sha256")
        # Which editions the answer used, so the audit can always tell. Never the question or answer text.
        AnswerRecord.objects.create(
            audit_event=event,
            status=result.status,
            public_reason=answered.public_reason or "",
            model=result.model,
            citations=[{k: by_id[c["passage_id"]][k] for k in edition} for c in result.citations],
            sources=[{k: s[k] for k in edition} for s in answered.sources],
            turn=turn,
            retries=result.retries,
            budget=result.budget or {},
            prompt_tokens=(result.usage or {}).get("prompt_tokens", 0),
            output_tokens=(result.usage or {}).get("output_tokens", 0),
        )
        if result.status in ERRORS:
            raise AssistantError(*ERRORS[result.status])
        nxt = answered.history
        return Response(
            {
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
                "budget": result.budget,
                "retries": result.retries,
                "history": dump_history(nxt),
                "conversation": {
                    "turn": turn,
                    "max_turns": MAX_TURNS,
                    "tokens_used": nxt.tokens_used,
                    "token_cap": CONVERSATION_TOKENS,
                },
                "disclaimer": DISCLAIMER,
            }
        )
