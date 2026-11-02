"""One consistent JSON error shape for the whole API.

{"error": {"code": "validation_error", "message": "...", "details": {...}}}
"""

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.db import DatabaseError
from django.http import Http404, JsonResponse
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class Conflict(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "The request conflicts with the current state of the resource."
    default_code = "conflict"


logger = logging.getLogger(__name__)


def envelope(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def error_response(code: str, message: str, http_status: int, details: dict | None = None) -> Response:
    return Response(envelope(code, message, details), status=http_status)


def api_exception_handler(exc, context):
    # DRF's handler turns Django's Http404 / PermissionDenied into responses but leaves `exc`
    # untouched (no `.detail`). Convert up front so one code path builds the envelope.
    # Week 6 Step 7 (R3): a database outage is a calm, retryable 503, never a 500 page. Never the error text.
    if isinstance(exc, DatabaseError):
        logger.error("database unavailable", extra={"event": "database_unavailable"}, exc_info=exc)
        response = error_response(
            "service_unavailable", "The service is temporarily unavailable. Please try again shortly.", 503
        )
        response["Retry-After"] = "30"
        return response
    if isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)
    if response is None:  # unhandled -> Django's 500 handler (never leaks a traceback when DEBUG is off)
        return None

    if isinstance(exc, exceptions.ValidationError):
        data = response.data
        details = data if isinstance(data, dict) else {"non_field_errors": data}
        response.data = envelope("validation_error", "One or more fields are invalid.", details)
        return response

    detail = exc.detail
    if isinstance(detail, dict):  # e.g. simplejwt's InvalidToken
        message = str(detail.get("detail", exc.default_detail))
        code = str(detail.get("code", exc.default_code))
    elif isinstance(detail, list):
        message = "; ".join(str(item) for item in detail)
        code = exc.default_code
    else:
        message = str(detail)
        code = getattr(detail, "code", exc.default_code)

    details = {}
    if isinstance(exc, exceptions.Throttled) and exc.wait is not None:
        details["retry_after_seconds"] = int(exc.wait)
    response.data = envelope(code, message, details)
    return response


def csrf_failure(request, reason=""):
    return JsonResponse(
        envelope("csrf_failed", "CSRF verification failed.", {"reason": reason}),
        status=403,
    )


def not_found(request, exception=None):
    return JsonResponse(envelope("not_found", "Resource not found."), status=404)


def server_error(request):
    return JsonResponse(envelope("server_error", "Internal server error."), status=500)
