"""Week 6 Step 6: per-route latency and error metrics, and token totals, for the ops view (O3–O5).

Samples hold the route pattern, method, status, milliseconds and time only. Stored in the database so every
gunicorn worker contributes; pruned after RETENTION.
"""

import logging
import random
from datetime import timedelta

from django.db import DatabaseError
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from agent.models import AgentRun
from assistant.costs import cost_report
from assistant.models import AnswerRecord

from .models import RequestSample

RETENTION = timedelta(days=7)
PRUNE_CHANCE = 0.01
logger = logging.getLogger(__name__)


def record(route, method, status, ms):
    try:
        RequestSample.objects.create(route=route[:200], method=method[:8], status=status, ms=ms)
        if random.random() < PRUNE_CHANCE:
            RequestSample.objects.filter(created_at__lt=timezone.now() - RETENTION).delete()
    except DatabaseError:
        # Metrics must never break a request (for example during a database outage).
        logger.warning("metrics sample not stored")


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)


def routes(hours):
    rows = {}
    since = timezone.now() - timedelta(hours=hours)
    for route, method, status, ms in RequestSample.objects.filter(created_at__gte=since).values_list(
        "route", "method", "status", "ms"
    ):
        rows.setdefault((method, route), []).append((status, ms))
    out = []
    for (method, route), samples in sorted(rows.items(), key=lambda kv: -len(kv[1])):
        ms = [m for _, m in samples]
        n = len(samples)
        out.append(
            {
                "method": method,
                "route": route,
                "count": n,
                "p50_ms": percentile(ms, 0.50),
                "p95_ms": percentile(ms, 0.95),
                "rate_4xx": round(sum(400 <= s < 500 for s, _ in samples) / n, 3),
                "rate_5xx": round(sum(s >= 500 for s, _ in samples) / n, 3),
            }
        )
    return out


def tokens(hours):
    since = timezone.now() - timedelta(hours=hours)
    days = {}
    for row in (
        AnswerRecord.objects.filter(created_at__gte=since)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(p=Sum("prompt_tokens"), o=Sum("output_tokens"))
    ):
        days.setdefault(row["day"], {"assistant": cost_report(0, 0), "agent_tokens": 0})
        days[row["day"]]["assistant"] = cost_report(row["p"] or 0, row["o"] or 0)
    for row in (
        AgentRun.objects.filter(created_at__gte=since)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(t=Sum("tokens"))
    ):
        days.setdefault(row["day"], {"assistant": cost_report(0, 0), "agent_tokens": 0})
        days[row["day"]]["agent_tokens"] = row["t"] or 0
    return [{"day": d, **v} for d, v in sorted(days.items(), reverse=True)]


def ops(hours):
    rows = routes(hours)
    total = sum(r["count"] for r in rows)
    return {
        "window_hours": hours,
        "requests": total,
        "rate_5xx": round(sum(r["rate_5xx"] * r["count"] for r in rows) / total, 3) if total else 0.0,
        "routes": rows,
        "tokens_by_day": tokens(hours),
        "cost_note": "Local model: no per-call cost. Hosted equivalent uses illustrative prices, not a quote.",
    }
