# Load test (Week 6 Step 8)

Rules: [REQUIREMENTS.md](REQUIREMENTS.md), "Step 8 rules", committed before any measurement.

**Setup:**
- Locust 2.42.6, headless, against the local Compose backend (`127.0.0.1:8000`, gunicorn with 3 sync workers, PostgreSQL 16), signed in as the seeded admin.
- Workload, fixed and synthetic: 10 users, spawn rate 2/s, 0.1–0.5 s wait, 60 s per run; `POST /api/v1/predict/` (weight 3) and `GET /api/v1/clusters/` (weight 1).
- Each configuration: one 15 s warm-up, then 3 measured runs; the median run is reported. Raw CSVs are in [`loadtest/results/`](../loadtest/results/).
- Reproduce: `docker compose -f docker-compose.yml -f loadtest/docker-compose.loadtest.yml up -d --wait`, then `loadtest/run.sh <label>`. The overlay raises the two rate limits for the test only.

**Read the numbers as relative, not as capacity.** They come from a laptop running Docker in a 4-CPU VM, with DEBUG on (the local profile).

## Baseline

| Endpoint | p50 | p95 | Throughput | Errors |
|---|---|---|---|---|
| `POST /api/v1/predict/` | 15 ms | 27 ms | 22.4 req/s | 0 / 3975 |
| `GET /api/v1/clusters/` | 9 ms | 16 ms | 7.9 req/s | 0 / 1395 |

Throughput is set by the 10 users' wait time, not by the server: the server keeps up with 30 req/s. Profiling one prediction outside the server shows about 5 ms in scikit-learn's pipeline, mostly the column transformer. The rest is the database writes the app makes on purpose: the prediction log, the audit event and the Step 6 latency sample.

## The optimisation: more gunicorn workers (negative result, reverted)

- **Picked from the baseline:** predict had the higher p95. With 10 concurrent users and 3 sync workers, requests could queue, so the change was gunicorn's documented `2 × CPU + 1` = 9 workers.
- **Measured with the identical workload:**

| Endpoint | p95 before | p95 after | Change | Errors |
|---|---|---|---|---|
| `POST /api/v1/predict/` | 27 ms | **51 ms** | +89% (worse) | 0 / 3898 |
| `GET /api/v1/clusters/` | 16 ms | **26 ms** | +63% (worse) | 0 / 1365 |

- **Why it got worse:** 9 Python processes compete for 4 virtual CPUs that also run PostgreSQL, Redis, the worker and the frontend. Queuing was not the bottleneck, so more workers only added CPU contention.
- **Outcome:** it failed the committed 10% improvement rule, so it was **reverted**: 3 workers stay, still overridable with `GUNICORN_WORKERS`.
- **No second change was tried:** that would be tuning after seeing results. The profile points to the next candidates, left for future work:
  - batching the latency-sample writes;
  - a lighter inference path. This would change the model artifact, so it needs a new release under the Week 3 reproducibility rules.
