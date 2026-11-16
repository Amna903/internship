# Evidence replay (Week 4 review follow-up)

One line per headline number: where it comes from and how to regenerate it. Synthetic data throughout; the
supervised test numbers are exploratory (the test set informed the release decision). A test
(`tests/test_evidence_replay.py`) checks every value below still appears in the report it links to.

| claim | value | report | regenerate |
|---|---|---|---|
| Served model test PR-AUC (not accuracy: ranking of the 16% no-show minority) | 0.280 | [release-1.0.0.md](../backend/ml/reports/release-1.0.0.md) | `python -m ml.train` |
| PR-AUC floor (no-show rate) / oracle ceiling | 0.164 / 0.321 | [metrics.md](../backend/ml/reports/metrics.md) | `python -m ml.train` |
| Served model train vs validation PR-AUC (gap) | 0.287 vs 0.276 (+0.011, warning bar 0.05) | [metrics.md](../backend/ml/reports/metrics.md) | `python -m ml.train` |
| CV choice not shipped: logreg_raw vs served, one-SE | 0.275 vs 0.283 (SE 0.008) | [metrics.md](../backend/ml/reports/metrics.md) | `python -m ml.train` |
| Real data: K-Means silhouette vs shuffled-data bar | 0.169 vs 0.173 (no structure) | [clusters.md](../backend/ml/reports/clusters.md) | `python -m ml.cluster` |
| Real data: Ward silhouette vs shuffled-data bar | 0.130 vs 0.163 (no structure) | [clusters.md](../backend/ml/reports/clusters.md) | `python -m ml.cluster` |
| Positive control (planted habits): K-Means / Ward ARI | 0.518 / 0.179 | [clusters.md](../backend/ml/reports/clusters.md) | `python -m ml.cluster` |
| Assistant frozen benchmark | 17 / 18 (A6 fails) | [eval_report.md](../backend/assistant/eval/eval_report.md) | `python manage.py evaluate_assistant` (needs Ollama) |
| Relevance check, frozen relevance set (off-topic + reversal stopped; correct kept) | 5 / 12; 6 / 6 | [relevance_report.md](../backend/assistant/eval/relevance_report.md) | `python manage.py evaluate_relevance --frozen` |

**Split guards (instead of "no leakage"):** patient-grouped 60/20/20 split, and no patient in two parts
(`tests/test_ml_preprocess.py::test_no_patient_appears_in_two_parts`); ids, label and oracle probability never
features (`tests/test_ml_data.py::test_ids_label_and_oracle_are_never_features`); imputer and scaler fitted on
training rows only (`test_imputation_median_comes_from_training_split_only`,
`test_scaler_statistics_come_from_training_split_only`); CV folds are `StratifiedGroupKFold` on training rows
only; no single feature above 0.80 AUC alone (strongest `lead_time_days` 0.618, [eda.md](../backend/ml/reports/eda.md) §8).
These are the checks that were made; they reduce the risk of leakage, they don't prove there is none.

**One admitted limitation:** citation validity is not entailment. "Each appointment can be rescheduled at least
twice", citing "at most twice", is answered (`TestRemainingFailures`).

**One prompt/debug iteration with its verification:** the "at no cost" idiom. Run
`DJANGO_SETTINGS_MODULE=config.settings_test python scripts/demo_idiom_fix.py`: it shows the correct D3 answer
blocked before the fix (polarity mismatch), answered after, the two-phrase list, "no fee" still caught, and the
regression tests passing.
