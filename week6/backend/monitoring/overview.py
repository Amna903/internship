"""The admin audit page's data (Week 5 Step 12, D1–D5): ids, codes, versions and times only. No messages,
answers, document text, free-text tool arguments or emails."""

from django.conf import settings

from agent.models import AgentRun, PendingAction
from assistant.models import AnswerRecord, DocumentVersion, IndexJob
from audit.models import AuditEvent

from . import drift

N = 25


def _passages(rows) -> list[dict]:
    return [
        {"passage_id": p.get("passage_id"), "document_id": p.get("document_id"), "version": p.get("version")}
        for p in rows or []
    ]


def overview() -> dict:
    runs = [
        {
            "id": str(r.id),
            "status": r.status,
            "stopped_reason": r.stopped_reason or None,
            "kind": r.kind or None,
            "user_id": r.user_id,
            "model": r.model,
            "tool_calls": r.tool_calls,
            "tokens": r.tokens,
            "seconds": round(r.seconds, 2),
            "pending_action_id": str(r.pending_action_id) if r.pending_action_id else None,
            "steps": [
                {"n": s.get("n"), "state": s.get("state"), "tool": s.get("tool"), "code": s.get("code")}
                for s in r.steps
            ],
            "created_at": r.created_at,
        }
        for r in AgentRun.objects.order_by("-created_at")[:N]
    ]
    tool_calls = [
        {"tool_and_outcome": e.detail, "user_id": e.actor_id, "request_id": e.request_id, "created_at": e.created_at}
        for e in AuditEvent.objects.filter(action=AuditEvent.Action.AGENT_TOOL_CALLED)[:N]
    ]
    actions = [
        {
            "id": str(a.id),
            "tool": a.tool,
            "status": a.status,
            "proposed_by_agent": a.proposed_by_agent,
            "user_id": a.user_id,
            "created_at": a.created_at,
            "decided_at": a.decided_at,
            "booking_id": a.booking_id,
        }
        for a in PendingAction.objects.order_by("-created_at")[:N]
    ]
    versions = [
        {
            "document_id": v.document_id,
            "version": v.number,
            "status": v.status,
            "decided_by": v.decided_by_id,
            "decided_at": v.decided_at,
        }
        for v in DocumentVersion.objects.exclude(decided_at=None).order_by("-decided_at")[:N]
    ]
    answers = [
        {
            "id": a.id,
            "status": a.status,
            "model": a.model,
            "turn": a.turn,
            "sources": _passages(a.sources),
            "citations": _passages(a.citations),
            "created_at": a.created_at,
        }
        for a in AnswerRecord.objects.order_by("-created_at")[:N]
    ]
    jobs = [
        {
            "id": j.id,
            "document_id": j.version.document_id,
            "version": j.version.number,
            "status": j.status,
            "attempts": j.attempts,
            "max_attempts": j.max_attempts,
            "error_code": j.error_code or None,
            "requested_by": j.requested_by_id,
            "queued_at": j.queued_at,
            "finished_at": j.finished_at,
        }
        for j in IndexJob.objects.select_related("version")[:N]
    ]
    cfg = settings.ASSISTANT
    try:
        baseline = drift.load_baseline()["model_version"]
    except (OSError, ValueError, KeyError):
        baseline = None
    models = {
        "no_show_served": drift.SERVED,
        "monitoring_baseline": baseline,
        "llm_configured": "fake" if cfg["PROVIDER"] == "fake" else cfg["MODEL"],
        "embedder_configured": "fake" if cfg["EMBEDDER"] != "ollama" else cfg["EMBED_MODEL"],
        "llms_on_answers": sorted(set(AnswerRecord.objects.exclude(model="").values_list("model", flat=True))),
        "llms_on_agent_runs": sorted(set(AgentRun.objects.exclude(model="").values_list("model", flat=True))),
    }
    return {
        "agent_runs": runs,
        "agent_tool_calls": tool_calls,
        "approval_decisions": {"actions": actions, "document_versions": versions},
        "retrieval_sources": answers,
        "jobs": jobs,
        "model_versions": models,
        "monitoring": drift.summary(7),
    }
