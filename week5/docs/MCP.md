# MCP server: clinic tools over the Model Context Protocol (Week 5 Step 9)

The backend includes a real MCP server, built with the official Python SDK (`mcp==2.3.0`). It exposes the
agent's four **read** tools to a local MCP client such as MCP Inspector or Claude Desktop. The tools are
the same definitions the agent uses (`agent/registry.py`), and every call goes through the same `run_tool`. So
validation, authorisation, output caps, typed errors and audit work exactly as they do for the agent.

Code: `agent/mcp_server.py`, `agent/mcp_tokens.py`, `manage.py run_mcp_server`, `create_mcp_token`,
`revoke_mcp_token`. Tests: `tests/test_agent_mcp.py`. Rules: `docs/REQUIREMENTS.md`, "Step 9 rules".

## How to connect

1. An admin issues a token (default lifetime **8 hours**, at most 24):

   ```bash
   cd week5/backend && .venv/bin/python manage.py create_mcp_token --admin admin@example.test
   ```

   The command prints the token **once**, with its id and expiry. Only its SHA-256 is stored.
2. Point the MCP client at the server. For MCP Inspector:

   ```bash
   HEALTHPROFILE_MCP_TOKEN=<token> npx @modelcontextprotocol/inspector \
     week5/backend/.venv/bin/python week5/backend/manage.py run_mcp_server
   ```

   For Claude Desktop, add a server entry with the same command and the token under `env`.
3. Revoke the token when you are done, or straight away if it may have leaked:

   ```bash
   .venv/bin/python manage.py revoke_mcp_token <token id>
   ```

   It stops working on the next call.

## Permissions

- **Transport: stdio only.** The client starts the server as a local process. The server opens no network
  port, so there is no new remote endpoint.
- **Who the server acts as comes only from the token**, never from a tool argument. Every call re-checks that:
  - the token exists;
  - it isn't revoked or expired;
  - its account is still an active admin.

  A demoted or deactivated admin is refused on the very next call. No tool schema contains a user, role or
  permission field (a Week 5 Step 6 test walks every schema).
- **Read tools only:** `search_policies`, `check_availability`, `predict_no_show`, `cluster_summaries`. The
  write tool (`book_mock_appointment`) isn't exposed, and confirming a booking remains a human web endpoint.
  MCP clients can be set to approve tool calls automatically, so write access over MCP would add risk for no
  benefit.
- **Rate limit:** at most **30 calls per minute per token**. The counter lives in the database, so it holds
  across several server processes started with the same token. Over the limit, a call returns `rate_limited`
  and the tool doesn't run.

## Inputs

Each tool's input schema is the registry's (the search tool keeps its optional area filter for direct
callers). Arguments are validated against the schema before the tool runs:
- unknown keys are rejected;
- types and ranges are enforced;
- NaN and infinity are rejected;
- the prediction tool also applies the API's cross-field rules.

Invalid input returns `invalid_input`, naming the field and never echoing the value.

## Outputs

- A successful call returns **structured content**, checked against the tool's output schema, plus the same
  JSON as text.
- Each tool has an **output size cap**. A result over the cap is refused, never truncated.
- Passage text from `search_policies` is marked `"untrusted": true`. It is policy data, not instructions.
- Errors return `is_error` with a typed code and a fixed message:
  - from the tools: `invalid_input`, `not_allowed`, `unavailable`, `timeout`, `output_too_large`, `refused`;
  - from the token: `invalid`, `expired`, `revoked`, `not_admin`, `rate_limited`.

  Errors never include stack traces, file paths or upstream error text.

## Audit

- Each tool call writes the usual `agent.tool_called` event (tool name and outcome only), with the request id
  `mcp:<token id>`, so MCP calls can be told apart from agent calls.
- The token's own events (`mcp.token_issued`, `mcp.token_first_used`, `mcp.token_revoked`) hold the token id
  only. Never the token, the arguments or any output.

## Threat model

| Threat | What limits it |
|---|---|
| **The token sits in plain text in the MCP client's configuration or environment** (for example Claude Desktop's config file, or a shell history). Anyone who can read that file can use it **until it expires or is revoked**. | A short default lifetime (8 hours; at most 24). Revoke it with `revoke_mcp_token` as soon as you're done or suspect a leak. Read-only tools. The per-token rate limit. Every use is audited with the token id. Keep the config file private, and don't commit or share it. |
| A stolen token used at volume | 30 calls per minute per token, across processes; revocation; expiry. |
| A token for an admin who has since been demoted or deactivated | The role and active status are re-checked on every call. |
| Prompt injection through tool output (a policy passage telling the client's model to do something) | Passage text is marked untrusted. There are no write tools over MCP. The client's own model is outside this server's control, so treat tool output as data in the client too. |
| Identity smuggled into arguments ("act as admin2") | No identity fields in any schema, and extra keys are rejected. Identity comes only from the token. |
| The token store leaking | Only SHA-256 hashes are stored. Tokens are random (32 bytes) and can't be recovered from the hash. |
| Writing into the protocol stream | The stdio server prints nothing but MCP messages; logs go to stderr. |

**Not covered:** remote (HTTP) access, OAuth, and per-user consent prompts. They would be needed before
running this anywhere but on a single trusted machine.
