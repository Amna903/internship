"""Week 5 Step 12 (D1–D5): the admin audit page's endpoint. Every section is filled by a real flow (agent run
with a proposal, confirm, a document approval job, an assistant answer), and nothing textual leaks."""

import json

import pytest

from agent.registry import ToolContext, run_tool
from assistant.llm import FakeLLM

from .conftest import Browser, user_login
from .test_assistant_versions import DOCS, NEW, OLD, post, upload

URL = "/api/v1/audit/overview/"
SECRET_MESSAGE = "Please book Tuesday for Zebediah Quince"


@pytest.fixture
def filled(admin_browser, admin, monkeypatch):
    doc = upload(admin_browser, DOCS, "refunds.md", OLD, policy_area="billing").json()["id"]
    post(admin_browser, f"{DOCS}{doc}/approve/")
    upload(admin_browser, f"{DOCS}{doc}/versions/", "refunds.md", NEW)
    post(admin_browser, f"{DOCS}{doc}/versions/2/reject/")
    ctx = ToolContext(user=admin, request_id="t", embedder=None, llm=None, via_agent=False)
    run_tool("cluster_summaries", {"dataset": "real"}, ctx)
    fake = FakeLLM()
    fake.replies.append(
        json.dumps({"action": "finish", "kind": "decline", "answer": "I can't help with that.", "citations": []})
    )
    monkeypatch.setattr("assistant.llm.get_llm", lambda: fake)
    admin_browser.client.post(
        "/api/v1/agent/run/", {"message": SECRET_MESSAGE}, format="json", **admin_browser._csrf_headers()
    )
    return doc


@pytest.mark.django_db
class TestOverview:
    def test_every_section_is_present_and_filled_by_real_flows(self, admin_browser, filled):
        body = admin_browser.get(URL).json()
        assert body["jobs"][0]["status"] == "succeeded" and body["jobs"][0]["document_id"] == filled
        assert {(v["version"], v["status"]) for v in body["approval_decisions"]["document_versions"]} == {
            (1, "current"),
            (2, "rejected"),
        }
        assert body["agent_tool_calls"] and body["agent_runs"]
        assert body["model_versions"]["no_show_served"] == "no-show-1.0.0"
        assert body["model_versions"]["monitoring_baseline"] == "no-show-1.0.0"
        assert {"retrieval_sources", "monitoring"} <= set(body)

    def test_nothing_textual_leaks(self, admin_browser, admin, filled):
        text = admin_browser.get(URL).text
        for forbidden in (OLD, NEW, "Zebediah", "Quince", "Tuesday for", "I can't help", admin.email):
            assert forbidden not in text

    def test_members_and_anonymous_are_refused(self, browser, user):
        assert browser.client.get(URL).status_code in (401, 403)
        member = Browser()
        user_login(member, user.email)
        assert member.client.get(URL).status_code in (401, 403)
