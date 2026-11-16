"""Week 5 Step 9 (P1, P2): the MCP server, through the official SDK's in-process client, plus one real stdio
subprocess. Tokens (hashed, short-lived, revocable, re-checked on every call), the per-token rate limit, the
four read tools only, typed errors and audit. No language model."""

import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import anyio
import pytest
from asgiref.sync import async_to_sync
from django.core.management import call_command
from django.utils import timezone
from mcp import StdioServerParameters
from mcp.client.client import Client

from accounts.models import User
from agent import mcp_server, mcp_tokens
from agent.mcp_tokens import CALLS_PER_MINUTE, TokenRefused, issue, revoke
from agent.models import McpToken, McpTokenUse
from agent.registry import REGISTRY
from audit.models import AuditEvent

from .conftest import PASSWORD

BACKEND = Path(__file__).resolve().parents[1]


def with_client(token, body):
    """Driven through async_to_sync, so the server's thread-sensitive ORM work runs on this test's thread and
    sees its transaction (asgiref's documented behaviour); the server code is unchanged."""

    async def main():
        async with Client(mcp_server.build_server(token)) as client:
            return await body(client)

    return async_to_sync(main)()


def call(token, name, args=None):
    return with_client(token, lambda c: c.call_tool(name, args or {}))


def error(result):
    assert result.is_error
    return json.loads(result.content[0].text)["error"]


@pytest.fixture
def token(admin):
    return issue(admin)[0]


# ---------------- tools ----------------


@pytest.mark.django_db
class TestTools:
    def test_lists_exactly_the_four_read_tools_with_registry_schemas(self, token):
        tools = with_client(token, lambda c: c.list_tools()).tools
        assert sorted(t.name for t in tools) == [
            "check_availability",
            "cluster_summaries",
            "predict_no_show",
            "search_policies",
        ]
        for t in tools:
            assert t.input_schema == REGISTRY[t.name].input_schema and t.output_schema == REGISTRY[t.name].output_schema

    def test_a_call_returns_structured_content_and_text(self, token):
        r = call(token, "cluster_summaries", {"dataset": "real"})
        assert not r.is_error and r.structured_content["real"]["structure_found"] is False
        assert json.loads(r.content[0].text) == r.structured_content

    def test_availability_works_through_mcp(self, token):
        start = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = call(token, "check_availability", {"visit_type": "telehealth", "start_date": start, "days": 7})
        assert not r.is_error and r.structured_content["fictional"] is True

    def test_the_write_tool_is_not_exposed(self, token):
        r = call(
            token,
            "book_mock_appointment",
            {"visit_type": "telehealth", "date": "2026-12-01", "time": "09:00", "clinician": "Clinician B"},
        )
        assert error(r)["code"] == "invalid_input"

    @pytest.mark.parametrize("args", [{"dataset": "everything"}, {"user": "admin2"}, {"role": "admin"}])
    def test_invalid_or_identity_arguments_are_typed_errors(self, token, args):
        assert error(call(token, "cluster_summaries", args))["code"] == "invalid_input"

    def test_errors_never_carry_internal_details(self, token, monkeypatch):
        from agent import read_tools
        from ml.inference import ModelUnavailable

        def broken():
            raise ModelUnavailable("SHA-256 mismatch at /secret/path")

        monkeypatch.setattr(read_tools, "get_model", broken)
        args = {
            "lead_time_days": 5,
            "appointment_weekday": "monday",
            "appointment_hour": 10,
            "age_band": "35-44",
            "visit_type": "in_person",
            "booking_channel": "web",
            "reminder_sent": True,
            "prior_appointments": 4,
            "prior_no_shows": 0,
            "distance_km": 6.5,
        }
        r = call(token, "predict_no_show", args)
        assert error(r)["code"] == "unavailable" and "secret" not in r.content[0].text


# ---------------- tokens ----------------


@pytest.mark.django_db
class TestTokens:
    def test_only_the_hash_is_stored_and_the_default_lifetime_is_short(self, admin):
        token, row = issue(admin)
        assert token.startswith("hpmcp_") and token not in json.dumps(list(McpToken.objects.values()), default=str)
        assert row.token_sha256 == mcp_tokens.digest(token)
        assert timedelta(hours=7, minutes=59) < row.expires_at - timezone.now() <= timedelta(hours=8)

    @pytest.mark.parametrize("hours", [0, 25])
    def test_lifetime_is_bounded(self, admin, hours):
        with pytest.raises(ValueError):
            issue(admin, hours)

    def test_a_member_cannot_be_issued_a_token(self, user):
        with pytest.raises(TokenRefused):
            issue(user)

    @pytest.mark.parametrize("bad", ["", "nope", "hpmcp_" + "x" * 43, "hpmcp_" + "x" * 300])
    def test_invalid_tokens_are_refused_and_list_nothing(self, db, bad):
        assert error(call(bad, "cluster_summaries"))["code"] == "invalid"
        assert with_client(bad, lambda c: c.list_tools()).tools == []

    def test_expired_tokens_are_refused(self, admin, token):
        McpToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        assert error(call(token, "cluster_summaries"))["code"] == "expired"

    def test_a_revoked_token_stops_working_on_the_next_call(self, admin):
        token, row = issue(admin)
        assert not call(token, "cluster_summaries").is_error
        revoke(row.id)
        assert error(call(token, "cluster_summaries"))["code"] == "revoked"

    def test_a_demoted_or_deactivated_admin_is_refused_on_the_next_call(self, admin, token):
        assert not call(token, "cluster_summaries").is_error
        User.objects.filter(pk=admin.pk).update(role=User.Role.USER)
        assert error(call(token, "cluster_summaries"))["code"] == "not_admin"


# ---------------- rate limit ----------------


@pytest.mark.django_db
class TestRateLimit:
    def test_calls_over_the_limit_are_refused_and_the_tool_does_not_run(self, admin, token):
        async def many(client):
            return [await client.call_tool("cluster_summaries", {}) for _ in range(CALLS_PER_MINUTE + 2)]

        results = with_client(token, many)
        assert [r.is_error for r in results].count(False) == CALLS_PER_MINUTE
        assert error(results[-1])["code"] == "rate_limited"
        assert AuditEvent.objects.filter(action="agent.tool_called").count() == CALLS_PER_MINUTE

    def test_the_limit_is_per_token(self, admin, token):
        McpTokenUse.objects.create(
            token=McpToken.objects.get(), minute=timezone.now().replace(second=0, microsecond=0), calls=CALLS_PER_MINUTE
        )
        assert error(call(token, "cluster_summaries"))["code"] == "rate_limited"
        other = issue(admin)[0]
        assert not call(other, "cluster_summaries").is_error

    def test_the_budget_resets_the_next_minute(self, admin, token, monkeypatch):
        row = McpToken.objects.get()
        now = timezone.now().replace(second=30, microsecond=0)
        McpTokenUse.objects.create(token=row, minute=now.replace(second=0), calls=CALLS_PER_MINUTE)
        monkeypatch.setattr(mcp_tokens.timezone, "now", lambda: now)
        assert error(call(token, "cluster_summaries"))["code"] == "rate_limited"
        monkeypatch.setattr(mcp_tokens.timezone, "now", lambda: now + timedelta(minutes=1))
        assert not call(token, "cluster_summaries").is_error


# ---------------- audit and commands ----------------


@pytest.mark.django_db
def test_audit_marks_mcp_calls_and_token_events_with_ids_only(admin):
    token, row = issue(admin)
    call(token, "cluster_summaries")
    revoke(row.id)
    actions = list(AuditEvent.objects.order_by("id").values_list("action", "detail", "request_id"))
    assert [a for a, _, _ in actions] == [
        "mcp.token_issued",
        "mcp.token_first_used",
        "agent.tool_called",
        "mcp.token_revoked",
    ]
    assert all(rid == f"mcp:{row.id}" for _, _, rid in actions)
    assert token not in json.dumps(actions)


@pytest.mark.django_db
def test_commands_issue_once_and_revoke(admin, capsys):
    call_command("create_mcp_token", admin=admin.email, hours=2)
    out = capsys.readouterr().out
    token = out.strip().splitlines()[-1]
    row = McpToken.objects.get()
    assert row.token_sha256 == mcp_tokens.digest(token) and str(row.id) in out
    call_command("revoke_mcp_token", str(row.id))
    assert McpToken.objects.get().revoked_at is not None


@pytest.mark.django_db
def test_commands_refuse_members_and_unknown_ids(user):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("create_mcp_token", admin=user.email)
    with pytest.raises(CommandError):
        call_command("revoke_mcp_token", "not-a-uuid")


# ---------------- a real stdio server process ----------------


def test_a_real_stdio_server_lists_and_calls_tools(tmp_path):
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings_test",
        "DATABASE_URL": f"sqlite:///{tmp_path / 'mcp.sqlite3'}",
    }
    run = lambda *args: subprocess.run(
        [sys.executable, "manage.py", *args], cwd=BACKEND, env=env, check=True, capture_output=True, text=True
    )
    run("migrate", "-v0")
    run("shell", "-c", f"from accounts.models import User; User.objects.create_admin('mcp@example.test', '{PASSWORD}')")
    token = run("create_mcp_token", "--admin", "mcp@example.test", "--hours", "1").stdout.strip().splitlines()[-1]
    params = StdioServerParameters(
        command=sys.executable,
        args=["manage.py", "run_mcp_server"],
        cwd=str(BACKEND),
        env={**env, mcp_server.TOKEN_ENV: token},
    )

    async def main():
        async with Client(params) as client:
            tools = (await client.list_tools()).tools
            result = await client.call_tool("cluster_summaries", {"dataset": "control"})
            return tools, result

    tools, result = anyio.run(main)
    assert len(tools) == 4 and not result.is_error and result.structured_content["control"]["k"] >= 2
