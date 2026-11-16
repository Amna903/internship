import logging
import re
import time
import uuid

from django.contrib.sessions.middleware import SessionMiddleware
from django.db import DatabaseError

from .logging import request_id as current_request_id

_SAFE_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
access_log = logging.getLogger("access")
UNMETERED = ("/health/", "/ready/")


class RequestIDMiddleware:
    """Give every request an id (reuse a well-formed incoming X-Request-ID, else make one).

    The id is echoed in the response header and stored on audit events, so a log line, an audit
    row and a user's bug report can be matched up. Week 6 Step 6: it is also set as the logging context,
    and each API request writes one access log line and one latency sample (route pattern only).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request.request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = current_request_id.set(request.request_id)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = request.request_id
            if request.path.startswith("/api/"):
                self._record(request, response.status_code, (time.perf_counter() - started) * 1000)
            return response
        finally:
            current_request_id.reset(token)

    def _record(self, request, status, ms):
        match = getattr(request, "resolver_match", None)
        route = "/" + match.route if match else "unmatched"
        try:
            user = getattr(request, "user", None)
            user_id = user.pk if user is not None and user.is_authenticated else None
        except DatabaseError:  # Week 6 Step 7: during an outage, reading the session must not turn a 503 into a 500
            user_id = None
        access_log.info(
            "request",
            extra={
                "method": request.method,
                "route": route,
                "status": status,
                "duration_ms": round(ms, 1),
                "user_id": user_id,
            },
        )
        from monitoring.metrics import record

        record(route, request.method, status, ms)


class OutageSafeSessionMiddleware(SessionMiddleware):
    """Week 6 Step 7 (R3): if the session can't be read on the way out (database down), keep the calm 503 the
    view already built instead of turning it into a 500. Nothing is saved, as there is nothing to save to."""

    def process_response(self, request, response):
        try:
            return super().process_response(request, response)
        except DatabaseError:
            return response
