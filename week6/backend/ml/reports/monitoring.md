# Model monitoring evidence (Week 5 Step 11)

Synthetic data and a fictional clinic. These numbers describe the model's behaviour on synthetic inputs only and make no claim about real-world medical impact.

Baseline: `no-show-1.0.0` probabilities on the validation split, 10 bins. Windows: 3970 appointments from 1000 fresh synthetic patients (seed 20261102), scored through the same logging path as the API. Expectations were committed before this run.

| Window | Expected | Result | Met |
|---|---|---|---|
| No drift | PSI < 0.10 (stable) | PSI 0.0062 (stable) | yes |
| Planted drift (reminders off, lead time ×3) | PSI > 0.25 (possible drift) | PSI 0.7999 (possible drift) | yes |
| 30 calls, model unavailable | failure_rate flagged | failure rate 1.0, flags failure_rate | yes |

| Bin | Baseline | No drift | Drift |
|---|---|---|---|
| 0.0–0.1 | 0.2471 | 0.2584 | 0.1156 |
| 0.1–0.2 | 0.4840 | 0.4690 | 0.2393 |
| 0.2–0.3 | 0.2024 | 0.1884 | 0.3015 |
| 0.3–0.4 | 0.0505 | 0.0642 | 0.2088 |
| 0.4–0.5 | 0.0138 | 0.0166 | 0.0935 |
| 0.5–0.6 | 0.0020 | 0.0025 | 0.0325 |
| 0.6–0.7 | 0.0003 | 0.0005 | 0.0071 |
| 0.7–0.8 | 0.0000 | 0.0003 | 0.0018 |
| 0.8–0.9 | 0.0000 | 0.0000 | 0.0000 |
| 0.9–1.0 | 0.0000 | 0.0000 | 0.0000 |

Latency (no-drift window, this machine): p50 5.2 ms, p95 6.02 ms; baseline p95 5.27 ms. Latency is machine-specific and not part of the reproducibility checks.
