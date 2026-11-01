import re
import uuid

_SAFE_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class RequestIDMiddleware:
    """Give every request an id (reuse a well-formed incoming X-Request-ID, else make one).

    The id is echoed in the response header and stored on audit events, so a log line, an audit
    row and a user's bug report can be matched up.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request.request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response
