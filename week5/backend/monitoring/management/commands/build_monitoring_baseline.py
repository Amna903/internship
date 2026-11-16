"""Writes ml/reports/monitoring_baseline.json (Week 5 Step 11, rule 2): the served model's probabilities on the
validation split (seed 42) in 10 fixed bins, and a latency reference from 200 single-row predictions."""

import json
import time

import numpy as np
from django.core.management.base import BaseCommand

from ml import config
from ml.data import dataset_hash, generate
from ml.inference import get_model
from ml.split import split
from monitoring.drift import BASELINE, shares


class Command(BaseCommand):
    help = "Build the monitoring baseline from the validation split."

    def handle(self, *args, **options):
        df = generate()
        _, validation, _ = split(df)
        model = get_model()
        rows = validation[config.FEATURES].to_dict("records")
        probabilities = [r["no_show_probability"] for r in model.predict(rows)]
        timings = []
        for row in rows[:200]:
            started = time.perf_counter()
            model.predict([row])
            timings.append((time.perf_counter() - started) * 1000)
        baseline = {"model_version": model.version, "dataset_sha256": dataset_hash(df), "split": "validation",
                    "rows": len(rows), "bins": [round(i / 10, 1) for i in range(11)],
                    "shares": [round(s, 4) for s in shares(probabilities)],
                    "latency_ms": {"p50": round(float(np.percentile(timings, 50)), 2),
                                   "p95": round(float(np.percentile(timings, 95)), 2),
                                   "note": "single-row predictions timed on the build machine; machine-specific"}}
        BASELINE.write_text(json.dumps(baseline, indent=2) + "\n")
        self.stdout.write(f"wrote {BASELINE.name}: {len(rows)} validation rows")
