"""The MCP server (Week 5 Step 9): the four read tools over stdio, with the official Python SDK.

Rules in docs/REQUIREMENTS.md ("Step 9 rules"); permissions, inputs, outputs and the threat model are in
docs/MCP.md. The tool definitions come from the same registry the agent uses (agent/registry.py), and every
call goes through `run_tool`, so validation, authorisation, output caps, typed errors and audit are identical.

Who the server acts as comes only from the MCP access token in its environment (never a tool argument). The
token is re-checked on every call (unexpired, unrevoked, still an active admin) and counted against its
per-minute limit. There is no write tool: confirming a booking stays a human web endpoint.
"""

import json
import os

import mcp_types as types
from asgiref.sync import sync_to_async
from mcp.server import Server

from .mcp_tokens import TokenRefused, count_call, resolve
from .registry import MESSAGES, REGISTRY, ToolContext, run_tool

NAME = "healthprofile-clinic-tools"
TOKEN_ENV = "HEALTHPROFILE_MCP_TOKEN"
REFUSALS = {
    "invalid": "The MCP access token is not valid.",
    "expired": "The MCP access token has expired. Ask an admin for a new one.",
    "revoked": "The MCP access token was revoked.",
    "not_admin": "The account behind this MCP access token is not an active admin.",
    "rate_limited": "Too many calls with this MCP access token. Wait a minute and try again.",
}


def read_tools() -> list[str]:
    return [name for name, tool in REGISTRY.items() if tool.permission == "read"]


def tool_list() -> list[types.Tool]:
    return [
        types.Tool(
            name=name,
            description=REGISTRY[name].description,
            input_schema=REGISTRY[name].input_schema,
            output_schema=REGISTRY[name].output_schema,
        )
        for name in read_tools()
    ]


def _error(code: str, message: str) -> types.CallToolResult:
    body = {"ok": False, "error": {"code": code, "message": message}}
    return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(body))], is_error=True)


def call(token: str, name: str, arguments, embedder=None, llm=None) -> types.CallToolResult:
    """One MCP tool call, synchronously (the Django ORM is synchronous)."""
    try:
        row = resolve(token)
        count_call(row)
    except TokenRefused as exc:
        return _error(exc.code, REFUSALS[exc.code])
    if name not in read_tools():  # the write tool, or anything unknown, is not exposed here
        return _error("invalid_input", "No such tool on this server.")
    from assistant.embeddings import get_embedder
    from assistant.llm import get_llm

    ctx = ToolContext(
        user=row.user,
        request_id=f"mcp:{row.id}",
        embedder=embedder or get_embedder,
        llm=llm or get_llm,
        via_agent=False,
    )
    result = run_tool(name, arguments if arguments is not None else {}, ctx)
    if not result.ok:
        return _error(result.code, MESSAGES[result.code])
    text = json.dumps(result.output, ensure_ascii=False)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], structured_content=result.output)


def build_server(token: str, embedder=None, llm=None) -> Server:
    async def on_list_tools(ctx, params):
        refused = await sync_to_async(_check_token, thread_sensitive=True)(token)
        return types.ListToolsResult(tools=[] if refused else tool_list())

    async def on_call_tool(ctx, params):
        return await sync_to_async(call, thread_sensitive=True)(token, params.name, params.arguments, embedder, llm)

    return Server(NAME, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


def _check_token(token: str) -> str | None:
    try:
        resolve(token)
        return None
    except TokenRefused as exc:
        return exc.code


def token_from_env() -> str:
    return os.environ.get(TOKEN_ENV, "")
