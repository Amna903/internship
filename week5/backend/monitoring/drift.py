"""Prediction monitoring and drift (Week 5 Step 11; rules in docs/REQUIREMENTS.md, "Step 11 rules").

`predict_logged` is the one place both the API and the agent's tool get a prediction from, so every call is
logged (version, source, outcome, probability, latency; never inputs or the user). `summary` compares a
window of logs with the committed baseline: the population stability index on 10 fixed probability bins,
plus latency and failure-rate flags. Synthetic data only: no claim about real-world medical impact.
"""

import json
import math
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
from django.utils import timezone

from ml import config as ml_config
from ml.inference import ModelUnavailable, get_model

from .models import PredictionLog

BASELINE = Path(ml_config.ML_DIR) / "reports" / "monitoring_baseline.json"
BINS = 10
FLOOR = 1e-4
STABLE, DRIFT = 0.10, 0.25
MIN_ROWS = 100
FAILURE_RATE, MIN_CALLS = 0.05, 20
LATENCY_FACTOR = 3.0
SERVED = f"no-show-{ml_config.MODEL_VERSION}"  # the name the loaded model reports
DISCLAIMER = ("Synthetic data and a fictional clinic. These numbers describe the model's behaviour on synthetic "
              "inputs only and make no claim about real-world medical impact.")


def _log(source, outcome, started, version=SERVED, probability=None):
    PredictionLog.objects.create(model_version=version, source=source, outcome=outcome, probability=probability,
                                 latency_ms=(time.perf_counter() - started) * 1000)


def log_invalid(source: str) -> None:
    _log(source, PredictionLog.Outcome.INVALID_INPUT, time.perf_counter())


def predict_logged(validated: dict, source: str, loader=None):
    """(model, result) for one validated row; logs ok or failed. Raises ModelUnavailable like get_model().
    `loader` is the caller's own get_model, so each caller keeps its existing test seams."""
    started = time.perf_counter()
    try:
        model = (loader or get_model)()
        result = model.predict([validated])[0]
    except Exception:
        _log(source, PredictionLog.Outcome.FAILED, started)
        raise
    _log(source, PredictionLog.Outcome.OK, started, model.version, result["no_show_probability"])
    return model, result


def shares(probabilities) -> list[float]:
    """Share of predictions in each of 10 fixed bins of width 0.1 (1.0 falls in the last bin)."""
    p = np.clip(np.asarray(probabilities, dtype=float), 0, 1)
    counts = np.bincount(np.minimum((p * BINS).astype(int), BINS - 1), minlength=BINS)
    return (counts / max(len(p), 1)).tolist()


def psi(expected: list[float], actual: list[float]) -> float:
    """Population stability index, sum((a - e) * ln(a / e)), each share floored at 0.0001."""
    return float(sum((max(a, FLOOR) - max(e, FLOOR)) * math.log(max(a, FLOOR) / max(e, FLOOR))
                     for e, a in zip(expected, actual)))


def verdict(value: float | None) -> str:
    if value is None:
        return "not enough data"
    return "stable" if value < STABLE else "watch" if value <= DRIFT else "possible drift"


def load_baseline() -> dict:
    return json.loads(BASELINE.read_text())


def summarise(rows: list[tuple[str, str, float | None, float]], baseline: dict) -> dict:
    """rows: (model_version, outcome, probability, latency_ms)."""
    calls = [r for r in rows if r[1] != PredictionLog.Outcome.INVALID_INPUT]
    ok = [r for r in rows if r[1] == PredictionLog.Outcome.OK]
    failed = sum(r[1] == PredictionLog.Outcome.FAILED for r in rows)
    other_versions = sorted({r[0] for r in ok} - {baseline["model_version"]})
    comparable = [r[2] for r in ok if r[0] == baseline["model_version"]]
    value = psi(baseline["shares"], shares(comparable)) if len(comparable) >= MIN_ROWS else None
    latencies = [r[3] for r in ok]
    p50 = float(np.percentile(latencies, 50)) if latencies else None
    p95 = float(np.percentile(latencies, 95)) if latencies else None
    rate = failed / len(calls) if calls else None
    flags = []
    if value is not None and value > DRIFT:
        flags.append("possible_drift")
    if rate is not None and len(calls) >= MIN_CALLS and rate > FAILURE_RATE:
        flags.append("failure_rate")
    if p95 is not None and p95 > LATENCY_FACTOR * baseline["latency_ms"]["p95"]:
        flags.append("latency")
    if other_versions:
        flags.append("baseline_is_for_another_version")
    return {"predictions": len(ok), "invalid_input": len(rows) - len(calls), "failed": failed,
            "failure_rate": None if rate is None else round(rate, 4),
            "shares": [round(s, 4) for s in shares(comparable)] if comparable else None,
            "baseline_shares": baseline["shares"], "psi": None if value is None else round(value, 4),
            "verdict": verdict(value), "latency_ms": {"p50": p50 and round(p50, 2), "p95": p95 and round(p95, 2)},
            "baseline_latency_ms": baseline["latency_ms"], "model_version": baseline["model_version"],
            "other_versions": other_versions, "flags": flags, "disclaimer": DISCLAIMER}


def summary(days: int = 7) -> dict:
    since = timezone.now() - timedelta(days=days)
    rows = list(PredictionLog.objects.filter(created_at__gte=since)
                .values_list("model_version", "outcome", "probability", "latency_ms"))
    return {"days": days, **summarise(rows, load_baseline())}
