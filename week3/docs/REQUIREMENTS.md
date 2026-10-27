# Week 3 requirement → evidence checklist

Source: **"WEEK 3 | Machine Learning Pipeline and Prediction API"** in *Elevate Engine Full-Stack AI/ML Weeks 2–6* (the full-stack brief, not the frontend one). Each row is one line of that brief, worded as in the brief.

Fill in each row as the work is done:
- **Code:** where it's implemented.
- **Test:** the automated test that proves it, or "manual" plus what you checked.
- **Demo:** the Loom timestamp.
- **Me:** the date you re-ran the check yourself. Leave it blank until you have.

Status: ☐ not started · ◐ in progress · ☑ done and evidenced.

## Task decision (Step 0)

**Task: synthetic appointment no-show likelihood.** It's binary classification: will a fictional appointment be missed?

Why this task:
- **Non-diagnostic.** It predicts attendance, not health. The brief names it as its example.
- **Easy to keep fully synthetic** with a seeded generator, so there's no licence or approval question.
- **Has a realistic class imbalance** (no-shows are the minority), which tests the metric choice and makes the imbalance worth documenting.
- **The output supports a low-risk action only**, for example sending an extra reminder. A wrong prediction harms no one clinically.

Rejected alternatives: anything predicting a condition, symptom or risk of illness (diagnostic, against the brief); public health datasets (they need provenance and licence checks and may contain sensitive fields).

## Features

| # | Requirement (brief wording) | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|
| F1 | Choose synthetic or explicitly approved public non-sensitive data | ☑ | `backend/ml/data.py` (seeded NumPy generator) | `tests/test_ml_data.py::test_schema_is_exactly_ids_features_oracle_and_label` | | |
| F2 | Document provenance, license, schema and limitations | ☑ | [DATA_CARD.md](DATA_CARD.md) | manual: every section present | | |
| F3 | Perform exploratory analysis | ☑ | `backend/ml/eda.py` → [ml/reports/eda.md](../backend/ml/reports/eda.md) | `tests/test_ml_eda.py` (8 tests: deterministic, up to date, numbers match the data) | | |
| F4 | Missing-value handling | ☑ | `ml/preprocess.py`: `SimpleImputer(median, add_indicator=True)` fitted on train only; analysis in eda.md §3 | `test_imputation_median_comes_from_training_split_only`, `test_output_has_no_missing_values_and_a_missing_flag` | | |
| F5 | Train/validation/test split | ☑ | `ml/split.py`: 60/20/20 `GroupShuffleSplit` by `patient_id`, seed 42 (`python -m ml.split`) | `test_no_patient_appears_in_two_parts`, `test_every_row_lands_in_exactly_one_part`, `test_split_is_reproducible`, `test_parts_are_roughly_60_20_20_and_representative` | | |
| F6 | Train a baseline scikit-learn model for a non-diagnostic task | ☑ | `ml/models.py`: floor `DummyClassifier`; baseline `LogisticRegression` on raw features (no-show likelihood, not diagnostic) | `test_every_real_model_beats_the_floor_on_validation` | | |
| F7 | At least one improved scikit-learn model | ☑ | `ml/models.py`: logistic regression + engineered features (chosen) and `HistGradientBoostingClassifier` | `test_report_states_whatever_the_improvement_numbers_show` (bootstrap 95% CI, verdict computed, not forced), `test_the_grid_covers_floor_baseline_and_two_improved_families`, `test_full_model_survives_joblib_save_and_reload_in_a_fresh_process` | | |
| F8 | Compare models with appropriate metrics | ☑ | [metrics.md](../backend/ml/reports/metrics.md): PR-AUC, ROC-AUC, Brier, threshold metrics, oracle ceiling, bootstrap CI; calibration in [errors.md](../backend/ml/reports/errors.md) §2 | `tests/test_ml_train.py`, `test_report_states_the_calibration_verdict_that_the_numbers_give` | | |
| F9 | Error analysis | ☑ | `ml/errors.py` → [errors.md](../backend/ml/reports/errors.md): confusion matrix with costs, noise-aware calibration, errors per group, unavoidable vs model errors, learned directions, confident mistakes | `tests/test_ml_errors.py` (15 tests, incl. hand-checked numbers and no dependence on test labels) | | |
| F10 | Prevent data leakage | ☑ | Column roles + `ColumnGuard`; patient-grouped split; train-only fitting; choices on validation only; test scored once (`evaluate_on_test`) | `tests/test_ml_preprocess.py`; `test_choice_and_threshold_do_not_depend_on_test_labels`, `test_test_set_is_scored_in_exactly_one_place`, `test_no_model_beats_the_oracle_ceiling` | | |
| F11 | Expose a versioned inference endpoint | ☐ | | | | |
| F12 | Show model output in the HealthTech dashboard | ☐ | | | | |

## Engineering constraints

| # | Requirement | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|
| E1 | Do not claim clinical validity or provide medical diagnosis | ☐ | | | | |
| E2 | Save preprocessing and model together in a reproducible pipeline | ☑ | `ml/artifact.py` → `ml/artifacts/no-show-1.0.0.joblib` (guard + features + preprocessing + model in one Pipeline) + `.json` metadata | `test_committed_model_equals_a_freshly_trained_one`, `test_committed_file_loads_in_a_fresh_process` | | |
| E3 | Validate inference schema | ☐ | | | | |
| E4 | Handle malformed and out-of-range inputs | ☐ | | | | |
| E5 | Pin dependencies | ☑ | `backend/requirements.txt` exact `==` pins; versions recorded in the metadata; loader refuses a different scikit-learn | `test_pinned_requirements_match_the_versions_the_model_was_built_with`, `test_wrong_scikit_learn_version_is_refused` | | |
| E6 | Record random seeds | ☑ | `SEED = 42` (`ml/config.py`) drives data, split and every model (`random_state`); recorded in DATA_CARD and metrics.md | `test_same_seed_gives_identical_data`, `test_split_is_reproducible`, `test_training_is_deterministic` | | |
| E7 | Document class imbalance | ☑ | DATA_CARD "Class imbalance" (16.4%) | `test_class_imbalance_is_in_the_documented_band` | | |
| E8 | Document dataset bias | ☑ | DATA_CARD "Bias" with measured model numbers; errors.md §4 (gaps, mitigation options: drop age analysed, per-group thresholds rejected, supportive use adopted) | `test_age_bias_is_present`, `test_fairness_gaps_by_hand`, `test_analysis_does_not_depend_on_test_labels` | | |

## Acceptance checks

| # | Check | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|
| A1 | Training script can reproduce model artifact | ☑ | `python -m ml.artifact`; reproducibility levels 1–4 in README | `test_rebuild_reproduces_data_metrics_and_predictions` (fresh process), `test_rebuild_is_byte_identical_on_the_same_platform` | | |
| A2 | Inference API returns validated output and model version | ☐ | | | | |
| A3 | README includes metrics, dataset limitations and sample request/response | ☐ | | | | |

## Required submission

| # | Item | Status |
|---|---|---|
| S1 | GitHub repository with meaningful commit history and clear setup instructions | ☐ |
| S2 | README: feature checklist, architecture decisions, run/test commands, limitations, screenshots or API examples | ☐ |
| S3 | Loom 5–10 min: working demo; key files and architecture; actual prompts and refinements; context management; blast-radius boundaries; debugging and verification of generated changes | ☐ |
| S4 | Repository and Loom links posted in the team channel by Tuesday 11:59 PM PKT; daily progress and blockers shared | ☐ |

## Carried forward (implementation note: "keep existing features working")

| # | Item | Status | Evidence |
|---|---|---|---|
| K1 | Week 1 and Week 2 features still work after copying Week 2 into `week3/` | ☑ | 2026-10-21, run by Claude Code: `pytest` 192 passed + 1 PostgreSQL-only skip (SQLite), 193 passed (PostgreSQL 14.21); `npm test` 37 passed; typecheck and `next build` clean. CI covers `week3/` on every push. |
| K2 | Week 2 checklist still valid | ☑ | [REQUIREMENTS-week2.md](REQUIREMENTS-week2.md) |
| K3 | New ML endpoints follow the same rules: admin session only, CSRF, rate limit, audit event without input values | ☐ | |
