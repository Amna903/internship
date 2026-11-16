"""Week 5 Step 6 (T1-T5): the typed tool registry and the four read tools.

Security rules first (identity only from the server-side context, no identity fields in any schema,
authorisation on every call, output caps, typed failures, audit without arguments), then each tool.
Fake embedder; the real served model and committed cluster results; a fixed clock."""

import dataclasses
import json
import math
from datetime import date

import pytest
from django.core.management import call_command

from accounts.models import User
from agent import read_tools, registry
from agent.registry import REGISTRY, ToolContext, run_tool
from assistant import answering
from assistant.embeddings import FakeEmbedder
from assistant.llm import LLMUnavailable
from audit.models import AuditEvent
from ml import config as ml_config
from ml.inference import ModelUnavailable, get_model

TODAY = date(2026, 11, 2)  # a Monday
FORBIDDEN = {"user", "user_id", "userid", "username", "role", "roles", "permission", "permissions", "is_admin",
             "admin", "actor", "owner", "account", "email", "token", "auth", "authorization", "scope", "caller",
             "as_user", "impersonate", "privilege", "privileges", "group", "groups"}
GOOD_PREDICTION = {"lead_time_days": 10, "appointment_weekday": "monday", "appointment_hour": 10, "age_band": "25-34",
                   "visit_type": "in_person", "booking_channel": "app", "reminder_sent": True, "prior_appointments": 3,
                   "prior_no_shows": 1, "distance_km": None}


@pytest.fixture
def ctx(admin):
    return ToolContext(user=admin, request_id="req-1", today=lambda: TODAY, embedder=FakeEmbedder)


def property_names(schema: dict):
    for name, sub in schema.get("properties", {}).items():
        yield name
        yield from property_names(sub)
    if "items" in schema:
        yield from property_names(schema["items"])


def objects(schema: dict):
    if schema.get("type") == "object":
        yield schema
    for sub in schema.get("properties", {}).values():
        yield from objects(sub)
    if "items" in schema:
        yield from objects(schema["items"])


# ---------------- the registry and its security rules ----------------

def test_the_four_read_tools_plus_the_one_step7_write_tool_all_admin_only():
    reads = sorted(n for n, t in REGISTRY.items() if t.permission == "read")
    assert reads == ["check_availability", "cluster_summaries", "predict_no_show", "search_policies"]
    assert [n for n, t in REGISTRY.items() if t.permission == "write"] == ["book_mock_appointment"]
    assert all(t.roles == ("admin",) for t in REGISTRY.values())


@pytest.mark.parametrize("tool", list(REGISTRY.values()), ids=lambda t: t.name)
def test_no_tool_schema_carries_identity_role_or_permission(tool):
    """Identity and role come only from the server-side ToolContext, never from tool arguments."""
    for schema in (tool.input_schema, tool.output_schema):
        names = {n.lower() for n in property_names(schema)}
        assert not names & FORBIDDEN, names & FORBIDDEN


@pytest.mark.parametrize("tool", list(REGISTRY.values()), ids=lambda t: t.name)
def test_every_input_object_forbids_extra_keys_so_identity_cant_be_smuggled_in(tool, ctx):
    assert all(o.get("additionalProperties") is False for o in objects(tool.input_schema))
    r = run_tool(tool.name, {"user": "root@example.test", "role": "admin"}, ctx)
    assert not r.ok and r.code == "invalid_input"


@pytest.mark.parametrize("tool", list(REGISTRY.values()), ids=lambda t: t.name)
def test_specs_are_short_and_carry_no_secrets(tool):
    spec = json.dumps(tool.spec()).lower()
    assert len(tool.description) <= 300
    for word in ("password", "secret", "api key", "token", "system prompt"):
        assert word not in spec


def test_handlers_take_no_identity_from_arguments():
    """Every handler is (args, ctx): who is calling can only be read from ctx.user."""
    import inspect
    for tool in REGISTRY.values():
        assert list(inspect.signature(tool.handler).parameters) == ["args", "ctx"]


@pytest.mark.django_db
class TestAuthorisation:
    @pytest.mark.parametrize("name", list(REGISTRY))
    def test_a_member_is_not_allowed_and_nothing_runs(self, name, user):
        built = []
        c = ToolContext(user=user, today=lambda: TODAY, embedder=lambda: built.append(1) or FakeEmbedder())
        r = run_tool(name, {}, c)
        assert not r.ok and r.code == "not_allowed" and built == []

    def test_anonymous_and_missing_callers_are_not_allowed(self):
        from django.contrib.auth.models import AnonymousUser
        for who in (None, AnonymousUser()):
            assert run_tool("cluster_summaries", {}, ToolContext(user=who)).code == "not_allowed"

    def test_a_deactivated_admin_is_not_allowed(self, admin):
        admin.is_active = False
        assert run_tool("cluster_summaries", {}, ToolContext(user=admin)).code == "not_allowed"

    def test_authorisation_reads_the_role_from_the_context_user_on_every_call(self, admin, ctx):
        assert run_tool("cluster_summaries", {}, ctx).ok
        admin.role = User.Role.USER  # e.g. demoted between two steps of one agent run
        assert run_tool("cluster_summaries", {}, ctx).code == "not_allowed"


@pytest.mark.django_db
class TestFailuresAndAudit:
    def test_one_audit_event_per_call_with_tool_and_outcome_never_the_arguments(self, ctx):
        run_tool("search_policies", {"query": "What dose of ibuprofen should I take?"}, ctx)
        run_tool("check_availability", {"visit_type": "telehealth", "start_date": "2026-11-03"}, ctx)
        events = list(AuditEvent.objects.filter(action="agent.tool_called").order_by("id"))
        assert [e.detail for e in events] == ["search_policies:refused", "check_availability:ok"]
        assert all(e.request_id == "req-1" for e in events)
        assert "ibuprofen" not in json.dumps(list(AuditEvent.objects.values()), default=str)

    def test_a_refused_member_call_is_audited_too(self, user):
        run_tool("cluster_summaries", {}, ToolContext(user=user))
        assert AuditEvent.objects.get(action="agent.tool_called").detail == "cluster_summaries:not_allowed"

    def test_unknown_tool_is_invalid_input(self, ctx):
        assert run_tool("delete_everything", {}, ctx).code == "invalid_input"

    @pytest.mark.parametrize("args", [None, [], "x", 5])
    def test_arguments_must_be_an_object(self, ctx, args):
        assert run_tool("cluster_summaries", args, ctx).code == "invalid_input"

    def test_failure_messages_are_fixed_and_never_carry_internal_details(self, ctx, monkeypatch):
        def boom(*a, **k):
            raise LLMUnavailable("connection refused to 10.0.0.5:11434")
        monkeypatch.setattr(read_tools, "shipped_retrieve", boom)
        r = run_tool("search_policies", {"query": "How long do refunds take?"}, ctx)
        assert r.code == "unavailable" and "10.0.0.5" not in json.dumps(r.public())
        assert r.public()["error"]["message"] == registry.MESSAGES["unavailable"]

    def test_output_over_the_cap_is_refused_not_truncated(self, ctx, monkeypatch):
        small = dataclasses.replace(REGISTRY["cluster_summaries"], max_output_chars=50)
        monkeypatch.setitem(REGISTRY, "cluster_summaries", small)
        r = run_tool("cluster_summaries", {}, ctx)
        assert not r.ok and r.code == "output_too_large" and r.output is None

    def test_a_handler_output_that_breaks_its_schema_is_never_passed_on(self, ctx, monkeypatch):
        bad = dataclasses.replace(REGISTRY["cluster_summaries"], handler=lambda a, c: {"results_version": 1})
        monkeypatch.setitem(REGISTRY, "cluster_summaries", bad)
        assert run_tool("cluster_summaries", {}, ctx).code == "unavailable"

    def test_a_result_after_the_deadline_is_discarded(self, ctx, monkeypatch):
        slow = dataclasses.replace(REGISTRY["cluster_summaries"], timeout_seconds=0.0)
        monkeypatch.setitem(REGISTRY, "cluster_summaries", slow)
        r = run_tool("cluster_summaries", {}, ctx)
        assert r.code == "timeout" and r.output is None

    def test_non_finite_numbers_are_invalid(self, ctx):
        assert run_tool("predict_no_show", {**GOOD_PREDICTION, "distance_km": math.nan}, ctx).code == "invalid_input"
        assert run_tool("predict_no_show", {**GOOD_PREDICTION, "distance_km": math.inf}, ctx).code == "invalid_input"


# ---------------- search_policies (T2) ----------------

@pytest.mark.django_db
class TestSearch:
    @pytest.fixture(autouse=True)
    def policies(self, admin, monkeypatch):
        call_command("load_policies", admin=admin.email)
        # the tuned floor belongs to the real embedder; a low one lets the fake return passages
        monkeypatch.setattr(read_tools, "load_tuned", lambda: {"floor": 0.0, "top_k": 5, "groundedness_threshold": 0.61})

    def test_returns_at_most_three_passages_with_edition_and_an_untrusted_flag(self, ctx):
        r = run_tool("search_policies", {"query": "How long do I have to request a refund?"}, ctx)
        assert r.ok and 1 <= len(r.output["passages"]) <= 3 and r.output["untrusted"] is True
        assert {"passage_id", "document", "version", "text", "score"} == set(r.output["passages"][0])

    def test_uses_the_shipped_retrieval_with_the_area_filter(self, ctx, monkeypatch):
        seen = {}
        real = read_tools.shipped_retrieve
        monkeypatch.setattr(read_tools, "shipped_retrieve",
                            lambda q, llm, emb, tuned, area=None: seen.update(q=q, area=area) or real(q, llm, emb, tuned, area=area))
        run_tool("search_policies", {"query": "refund", "area": "billing"}, ctx)
        assert seen == {"q": "refund", "area": "billing"}

    def test_the_query_is_redacted_before_retrieval(self, ctx, monkeypatch):
        seen = {}
        monkeypatch.setattr(read_tools, "shipped_retrieve", lambda q, *a, **k: seen.setdefault("q", q) and
                            __import__("assistant.indexing", fromlist=["x"]).SearchResult([], [], 0, 0))
        run_tool("search_policies", {"query": "Refund for jane@example.test, card 4111111111111111?"}, ctx)
        assert "jane@example.test" not in seen["q"] and "4111111111111111" not in seen["q"]

    def test_a_medical_query_is_refused_before_any_embedding(self, admin):
        built = []
        c = ToolContext(user=admin, embedder=lambda: built.append(1) or FakeEmbedder())
        assert run_tool("search_policies", {"query": "Which medicine should I take for my fever?"}, c).code == "refused"
        assert built == []

    @pytest.mark.parametrize("args", [{}, {"query": ""}, {"query": "x" * 501}, {"query": "ok", "area": "nope"},
                                      {"query": 5}, {"query": "   "}])
    def test_invalid_input(self, ctx, args):
        assert run_tool("search_policies", args, ctx).code == "invalid_input"

    def test_worst_case_output_fits_the_cap(self, ctx, monkeypatch):
        from assistant.models import Chunk
        longest = max(Chunk.objects.all(), key=lambda c: len(c.text))
        from assistant.indexing import SearchResult
        from assistant.prompts import Passage
        p = Passage(longest.passage_id, "x" * 40, longest.text)
        monkeypatch.setattr(read_tools, "shipped_retrieve", lambda *a, **k: SearchResult([p] * 5, [0.9] * 5, 0, 5))
        assert run_tool("search_policies", {"query": "anything"}, ctx).ok


# ---------------- check_availability (T3) ----------------

AVAIL = {"visit_type": "telehealth", "start_date": "2026-11-03", "days": 3}


@pytest.mark.django_db
class TestAvailability:
    def test_deterministic_with_a_fixed_clock(self, ctx):
        a, b = run_tool("check_availability", AVAIL, ctx), run_tool("check_availability", AVAIL, ctx)
        assert a.ok and a.output == b.output and a.output["fictional"] is True
        assert a.output["slots"][0] == {"date": "2026-11-03", "time": "09:00", "visit_type": "telehealth",
                                        "clinician": "Clinician B"}  # pinned: the schedule is a fixed function

    def test_at_most_ten_slots_earliest_first(self, ctx):
        out = run_tool("check_availability", {**AVAIL, "days": 14}, ctx).output
        keys = [(s["date"], s["time"]) for s in out["slots"]]
        assert len(out["slots"]) == 10 and out["more_available"] and keys == sorted(keys)

    def test_weekends_are_closed_and_part_of_day_is_respected(self, ctx):
        sat = run_tool("check_availability", {**AVAIL, "start_date": "2026-11-07", "days": 2}, ctx).output
        assert sat["slots"] == [] and not sat["more_available"]
        pm = run_tool("check_availability", {**AVAIL, "part_of_day": "afternoon"}, ctx).output
        assert pm["slots"] and all(s["time"] >= "12:00" for s in pm["slots"])

    def test_clinicians_are_fictional_and_match_the_visit_type(self, ctx):
        out = run_tool("check_availability", {**AVAIL, "visit_type": "in_person", "days": 14}, ctx).output
        assert {s["clinician"] for s in out["slots"]} <= {"Clinician A", "Clinician B", "Clinician C"}

    @pytest.mark.parametrize("start", ["2026-11-01", "2027-01-02", "2026-02-30", "02/11/2026"])
    def test_dates_in_the_past_beyond_60_days_or_malformed_are_invalid(self, ctx, start):
        assert run_tool("check_availability", {**AVAIL, "start_date": start}, ctx).code == "invalid_input"

    def test_the_horizon_moves_with_the_injected_clock(self, admin):
        later = ToolContext(user=admin, today=lambda: date(2026, 12, 1))
        assert run_tool("check_availability", {**AVAIL, "start_date": "2027-01-29"}, later).ok
        assert run_tool("check_availability", AVAIL, later).code == "invalid_input"  # now in the past

    @pytest.mark.parametrize("args", [{**AVAIL, "days": 15}, {**AVAIL, "days": 0}, {**AVAIL, "visit_type": "home"},
                                      {"visit_type": "telehealth"}, {**AVAIL, "part_of_day": "night"}])
    def test_invalid_input(self, ctx, args):
        assert run_tool("check_availability", args, ctx).code == "invalid_input"


# ---------------- predict_no_show (T4) ----------------

@pytest.mark.django_db
class TestPrediction:
    def test_the_same_answer_as_the_served_model_with_version_and_disclaimer(self, ctx):
        r = run_tool("predict_no_show", GOOD_PREDICTION, ctx)
        expected = get_model().predict([GOOD_PREDICTION])[0]
        assert r.ok and r.output["model_version"] == get_model().version == "no-show-1.0.0"
        assert r.output["no_show_probability"] == expected["no_show_probability"]
        assert r.output["disclaimer"] == ml_config.DISCLAIMER

    def test_the_input_schema_is_derived_from_the_apis_feature_spec(self):
        assert set(REGISTRY["predict_no_show"].input_schema["properties"]) == set(ml_config.FEATURE_SCHEMA)
        assert REGISTRY["predict_no_show"].input_schema["required"] == list(ml_config.FEATURE_SCHEMA)

    @pytest.mark.parametrize("change, field", [({"prior_no_shows": 4}, "$.prior_no_shows"),  # more than prior appointments
                                               ({"appointment_hour": 23}, "$.appointment_hour"),
                                               ({"appointment_weekday": "sunday"}, "$.appointment_weekday"),
                                               ({"reminder_sent": "yes"}, "$.reminder_sent")])
    def test_invalid_input_names_the_field_only(self, ctx, change, field):
        r = run_tool("predict_no_show", {**GOOD_PREDICTION, **change}, ctx)
        assert r.code == "invalid_input" and field in r.fields

    def test_a_missing_or_tampered_model_is_unavailable(self, ctx, monkeypatch):
        def broken():
            raise ModelUnavailable("SHA-256 does not match")
        monkeypatch.setattr(read_tools, "get_model", broken)
        r = run_tool("predict_no_show", GOOD_PREDICTION, ctx)
        assert r.code == "unavailable" and "SHA" not in json.dumps(r.public())


# ---------------- cluster_summaries (T5) ----------------

@pytest.mark.django_db
class TestClusters:
    def test_groups_only_never_individual_points(self, ctx):
        out = run_tool("cluster_summaries", {}, ctx).output
        text = json.dumps(out)
        assert "points" not in out.get("control", {}) and '"x"' not in text and "planted_habit" not in text
        assert out["real"]["structure_found"] is False and "should not be read as types of patient" in out["real"]["verdict"]
        assert "not categories of people" in out["note"]

    def test_groups_under_ten_are_hidden_and_counted(self, ctx, monkeypatch):
        from predictions import views
        view, digest = views.load_cluster_view()
        view = json.loads(json.dumps(view))
        view["control"]["clusters"][0]["size"] = 9
        monkeypatch.setattr(views, "load_cluster_view", lambda: (view, digest))
        out = run_tool("cluster_summaries", {"dataset": "control"}, ctx).output
        assert out["control"]["hidden_small_groups"] == 1 and all(g["size"] >= 10 for g in out["control"]["clusters"])
        assert "real" not in out

    def test_missing_results_are_unavailable(self, ctx, monkeypatch):
        from predictions import views
        monkeypatch.setattr(views, "load_cluster_view", lambda: (_ for _ in ()).throw(OSError("no file")))
        assert run_tool("cluster_summaries", {}, ctx).code == "unavailable"

    @pytest.mark.parametrize("dataset", ["control", "real", "both"])
    def test_each_dataset_choice_fits_the_cap(self, ctx, dataset):
        assert run_tool("cluster_summaries", {"dataset": dataset}, ctx).ok
