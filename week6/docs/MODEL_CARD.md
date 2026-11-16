# Model card: no-show likelihood 1.0.0 (D3)

Source of every figure: `backend/ml/artifacts/no-show-1.0.0.json` (the release metadata) and `backend/ml/reports/metrics.md`.

> **Educational prototype trained on synthetic data.** It estimates whether a fictional appointment may be missed, to help plan reminders. It is not a medical assessment and is not clinically validated.

| | |
|---|---|
| Version | `1.0.0`, artifact SHA-256 pinned in the metadata; served by `GET /api/v1/models/no-show/` |
| Task | Binary: will this (synthetic) appointment be a no-show? |
| Estimator | Logistic regression on engineered features (`logreg_engineered`, C=0.1), in one scikit-learn pipeline with its preprocessing (scaling, one-hot encoding, boolean cast), so the preprocessing is versioned with the model |
| Inputs | Lead time (days), weekday, hour, age band, visit type, booking channel, reminder sent, prior appointments, prior no-shows, distance (km). Fixed ranges and choices are validated by the API. |
| Output | Probability, and a suggested action: **extra reminder** if probability ≥ 0.1688, else standard reminder |
| Training data | Seeded synthetic generator `ml/data.py` (seed 42), data SHA-256 `f458e62a…`; split train 12,126 / validation 3,998 / test 3,952 rows; average no-show rate 16.5% |
| Libraries | Python 3.14.0, scikit-learn 1.9.1, pandas 3.0.6, numpy 2.5.4 |

## Performance (test set, scored once)

| | PR-AUC | ROC-AUC | Brier |
|---|---|---|---|
| **This model** | **0.280** | **0.663** | **0.1307** |
| Floor (always predict the average) | 0.164 | 0.500 | 0.1374 |
| Raw-feature logistic baseline | 0.267 | 0.649 | 0.1320 |
| Oracle ceiling (true generating probability) | 0.321 | 0.714 | 0.1264 |

At the threshold: precision 0.246, recall 0.597. Because the threshold is set for a cheap action (one extra reminder), it favours recall: about 3 in 4 extra reminders go to people who would have attended.

## Intended use and limits

- **For:** demonstrating an end-to-end, reproducible, monitored ML feature: planning *reminders* for a fictional clinic.
- **Not for:** any decision about a real person, care, triage, or denying or prioritising appointments.
- **Weak signal:** the gap to the oracle shows how much is achievable at most; even the oracle is modest, because no-shows are mostly random in the generator.
- **Age band is an input.** On real data this would need a fairness review, and per-group errors are in `ml/reports/errors.md`. Here the data is synthetic.
- **Drift:** monitored by PSI against the training baseline (`GET /api/v1/monitoring/`); a flag means investigate, not retrain automatically.
- **Reproducibility:** `python -m ml.verify_release` rebuilds the data, model and reports from scratch and compares them (a CI job; reproduced in the Step 9 suite).
