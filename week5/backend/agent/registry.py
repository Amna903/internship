"""The typed tool registry (Week 5 Step 6).

Every tool is declared once here: a name, a short description, input and output JSON schemas (checked by the
Step 5 validator, assistant/validation.py), a permission level, a deadline, a maximum output size and a
handler. The Step 8 agent and the Step 9 MCP server read these same definitions.

Security rules that hold for every tool, enforced here rather than in each handler:
- **Who is calling comes only from `ToolContext`**, which the server builds from the authenticated request.
  No tool schema may contain a user, role or permission field (tests/test_agent_tools.py checks every schema),
  so nothing a model writes into tool arguments can change who it acts as ("don't trust prompts to enforce
  security").
- **Authorisation is checked on every call**, inside `run_tool`, not only at an endpoint.
- Inputs are validated before the handler runs, and outputs after: a handler bug can't leak an unexpected
  shape. A result over the tool's size cap is refused (`output_too_large`), never silently truncated.
- Failures are typed results with a public code and a fixed message, never exceptions or internal details.
- One audit event per call: the tool name and the outcome code, never the arguments.

Deadlines: a slow call is ended by its own client timeout (embedder and model clients); a result that arrives
after the tool's deadline is discarded as `timeout`, so a late answer is never used.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace
from typing import Callable

from django.utils import timezone

from assistant.validation import SchemaError, validate
from audit.models import AuditEvent
from audit.services import record_event

logger = logging.getLogger(__name__)

CODES = ("invalid_input", "not_allowed", "unavailable", "timeout", "output_too_large", "refused")
MESSAGES = {
    "invalid_input": "The tool arguments are not valid.",
    "not_allowed": "You are not allowed to use this tool.",
    "unavailable": "The tool is temporarily unavailable.",
    "timeout": "The tool took too long to answer.",
    "output_too_large": "The tool result was too large to use.",
    "refused": "This tool does not answer that kind of request.",
}


class ToolFailure(Exception):
    """Raised by a handler to return a typed failure. `fields` names invalid arguments (names only)."""

    def __init__(self, code: str, fields: tuple = ()):
        assert code in CODES, code
        super().__init__(code)
        self.code, self.fields = code, tuple(fields)


@dataclass
class ToolContext:
    """Built by the server from the authenticated request, never from tool arguments."""

    user: object
    request_id: str = ""
    today: Callable[[], date] = field(default=lambda: timezone.localdate())  # injectable clock
    embedder: Callable = None  # factories, so a tool that doesn't need them never builds them
    llm: Callable = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    handler: Callable  # (args: dict, ctx: ToolContext) -> dict
    permission: str = "read"  # "read" or (Step 7) "write"
    roles: tuple = ("admin",)
    timeout_seconds: float = 30.0
    max_output_chars: int = 4000

    def spec(self) -> dict:
        """What a model (Step 8) or an MCP client (Step 9) is shown."""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class ToolResult:
    tool: str
    ok: bool
    output: dict | None = None
    code: str = ""  # one of CODES when not ok
    message: str = ""
    fields: tuple = ()
    seconds: float = 0.0

    def public(self) -> dict:
        if self.ok:
            return {"tool": self.tool, "ok": True, "output": self.output}
        return {"tool": self.tool, "ok": False, "error": {"code": self.code, "message": self.message,
                                                          **({"fields": list(self.fields)} if self.fields else {})}}


REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    assert tool.name not in REGISTRY, tool.name
    REGISTRY[tool.name] = tool
    return tool


def allowed(tool: Tool, user) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False) and getattr(user, "is_active", False)
                and getattr(user, "role", None) in tool.roles)


def _fail(tool: str, code: str, started: float, fields: tuple = ()) -> ToolResult:
    return ToolResult(tool=tool, ok=False, code=code, message=MESSAGES[code], fields=fields,
                      seconds=round(time.perf_counter() - started, 3))


def run_tool(name: str, args, ctx: ToolContext) -> ToolResult:
    started = time.perf_counter()
    tool = REGISTRY.get(name)
    if tool is None:
        return _fail(name[:40] if isinstance(name, str) else "?", "invalid_input", started)
    result = _run(tool, args, ctx, started)
    _audit(ctx, tool.name, result)
    return result


def _run(tool: Tool, args, ctx: ToolContext, started: float) -> ToolResult:
    if not allowed(tool, ctx.user):
        return _fail(tool.name, "not_allowed", started)
    try:
        validate(tool.input_schema, args)
    except SchemaError as exc:
        return _fail(tool.name, "invalid_input", started, fields=(str(exc).split(" ")[0],))
    try:
        output = tool.handler(args, ctx)
    except ToolFailure as exc:
        return _fail(tool.name, exc.code, started, fields=exc.fields)
    elapsed = time.perf_counter() - started
    if elapsed > tool.timeout_seconds:
        logger.warning("agent: tool %s finished after its deadline (%.1f s)", tool.name, elapsed)
        return _fail(tool.name, "timeout", started)
    try:
        validate(tool.output_schema, output)
    except SchemaError as exc:  # a handler bug: never pass an unexpected shape on
        logger.error("agent: tool %s output broke its schema (%s)", tool.name, exc)
        return _fail(tool.name, "unavailable", started)
    if len(json.dumps(output, ensure_ascii=False)) > tool.max_output_chars:
        return _fail(tool.name, "output_too_large", started)
    return ToolResult(tool=tool.name, ok=True, output=output, seconds=round(elapsed, 3))


def _audit(ctx: ToolContext, name: str, result: ToolResult) -> None:
    if ctx.user is None or not getattr(ctx.user, "is_authenticated", False):
        return  # nothing to attribute it to; the caller never got past authentication
    record_event(SimpleNamespace(user=ctx.user, request_id=ctx.request_id), AuditEvent.Action.AGENT_TOOL_CALLED,
                 detail=f"{name}:{'ok' if result.ok else result.code}"[:64])
