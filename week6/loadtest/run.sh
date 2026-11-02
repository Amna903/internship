#!/bin/sh
# Week 6 Step 8: one 15 s warm-up, then 3 measured 60 s runs of the fixed workload. Usage: loadtest/run.sh <label>
set -eu
cd "$(dirname "$0")"
LABEL=${1:?label, e.g. baseline}
LOCUST=${LOCUST:-locust}
HOST=${HOST:-http://127.0.0.1:8000}
$LOCUST -f locustfile.py --headless -u 10 -r 2 -t 15s --host "$HOST" --only-summary >/dev/null 2>&1 || true
for n in 1 2 3; do
  $LOCUST -f locustfile.py --headless -u 10 -r 2 -t 60s --host "$HOST" --only-summary \
    --csv "results/$LABEL-run$n" >/dev/null 2>&1 || true
  rm -f "results/$LABEL-run$n"_stats_history.csv "results/$LABEL-run$n"_exceptions.csv
done
python3 summarize.py "$LABEL"
