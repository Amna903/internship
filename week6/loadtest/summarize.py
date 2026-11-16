"""Median-of-3 summary for one labelled configuration (Week 6 Step 8). Usage: python3 summarize.py <label>"""

import csv
import statistics
import sys
from pathlib import Path

ENDPOINTS = ("POST /api/v1/predict/", "GET /api/v1/clusters/")


def rows(label):
    for path in sorted(Path(__file__).parent.glob(f"results/{label}-run*_stats.csv")):
        with path.open() as f:
            yield path.name, {r["Name"]: r for r in csv.DictReader(f)}


def main(label):
    runs = list(rows(label))
    print(f"{label}: {len(runs)} runs")
    for name in ENDPOINTS:
        stats = [r[name] for _, r in runs if name in r]
        p50 = statistics.median(float(s["50%"]) for s in stats)
        p95 = statistics.median(float(s["95%"]) for s in stats)
        rps = statistics.median(float(s["Requests/s"]) for s in stats)
        errors = sum(int(s["Failure Count"]) for s in stats)
        total = sum(int(s["Request Count"]) for s in stats)
        print(f"  {name}: median p50 {p50:.0f} ms, p95 {p95:.0f} ms, {rps:.1f} req/s; errors {errors}/{total}")


if __name__ == "__main__":
    main(sys.argv[1])
