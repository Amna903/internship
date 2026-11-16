"""The Step 11 evidence run (rule 6), deterministic and without a language model, in a rolled-back
transaction: no drift (fresh synthetic patients, seed 20261102), planted drift (reminders off, lead time x3)
and failures (model unavailable). Writes ml/reports/monitoring.md and monitoring.json."""

import json

from django.core.management.base import BaseCommand
from django.db import transaction

from ml import config
from ml.data import generate
from ml.inference import ModelUnavailable
from monitoring import drift
from monitoring.models import PredictionLog

SEED, PATIENTS, FAILURES = 20261102, 1000, 30
REPORT = drift.BASELINE.with_name("monitoring.md")
RESULT = drift.BASELINE.with_name("monitoring.json")
EXPECTED = {"no_drift": "PSI < 0.10 (stable)", "drift": "PSI > 0.25 (possible drift)",
            "failures": "failure_rate flagged"}


def shifted(row: dict) -> dict:
    return {**row, "reminder_sent": False, "lead_time_days": min(row["lead_time_days"] * 3, config.LEAD_TIME_MAX_DAYS)}


class Rollback(Exception):
    pass


def window(rows: list[dict]) -> dict:
    PredictionLog.objects.all().delete()
    for row in rows:
        drift.predict_logged(row, "api")
    return drift.summary(days=1)


def run() -> dict:
    base = generate(seed=SEED, n_patients=PATIENTS)[config.FEATURES].to_dict("records")
    out = {}
    try:
        with transaction.atomic():
            out["no_drift"] = window(base)
            out["drift"] = window([shifted(r) for r in base])
            PredictionLog.objects.all().delete()

            def down():
                raise ModelUnavailable("injected for the report")
            for row in base[:FAILURES]:
                try:
                    drift.predict_logged(row, "api", loader=down)
                except ModelUnavailable:
                    pass
            out["failures"] = drift.summary(days=1)
            raise Rollback
    except Rollback:
        pass
    met = {"no_drift": out["no_drift"]["verdict"] == "stable", "drift": out["drift"]["verdict"] == "possible drift",
           "failures": "failure_rate" in out["failures"]["flags"]}
    return {"seed": SEED, "patients": PATIENTS, "rows": len(base), "expected": EXPECTED, "met": met, "windows": out}


def report(r: dict) -> str:
    w = r["windows"]
    lines = ["# Model monitoring evidence (Week 5 Step 11)", "",
             drift.DISCLAIMER, "",
             f"Baseline: `{w['no_drift']['model_version']}` probabilities on the validation split, 10 bins. "
             f"Windows: {r['rows']} appointments from {r['patients']} fresh synthetic patients (seed {r['seed']}), "
             "scored through the same logging path as the API. Expectations were committed before this run.", "",
             "| Window | Expected | Result | Met |", "|---|---|---|---|"]
    for name, label in [("no_drift", "No drift"), ("drift", "Planted drift (reminders off, lead time ×3)"),
                        ("failures", f"{FAILURES} calls, model unavailable")]:
        s = w[name]
        got = (f"PSI {s['psi']} ({s['verdict']})" if name != "failures"
               else f"failure rate {s['failure_rate']}, flags {', '.join(s['flags']) or 'none'}")
        lines.append(f"| {label} | {r['expected'][name]} | {got} | {'yes' if r['met'][name] else '**no**'} |")
    lines += ["", "| Bin | Baseline | No drift | Drift |", "|---|---|---|---|"]
    for i in range(10):
        lines.append(f"| {i / 10:.1f}–{(i + 1) / 10:.1f} | {w['no_drift']['baseline_shares'][i]:.4f} | "
                     f"{w['no_drift']['shares'][i]:.4f} | {w['drift']['shares'][i]:.4f} |")
    lat = w["no_drift"]["latency_ms"]
    lines += ["", f"Latency (no-drift window, this machine): p50 {lat['p50']} ms, p95 {lat['p95']} ms; baseline p95 "
              f"{w['no_drift']['baseline_latency_ms']['p95']} ms. Latency is machine-specific and not part of the "
              "reproducibility checks.", ""]
    return "\n".join(lines)


class Command(BaseCommand):
    help = "Run the Step 11 monitoring evidence and write ml/reports/monitoring.md/.json."

    def handle(self, *args, **options):
        r = run()
        RESULT.write_text(json.dumps(r, indent=2) + "\n")
        REPORT.write_text(report(r))
        self.stdout.write(json.dumps(r["met"]))
