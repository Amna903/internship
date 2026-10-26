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
| F6 | Train a baseline scikit-learn model for a non-diagnostic task | ☐ | | | | |
| F7 | At least one improved scikit-learn model | ☐ | | | | |
| F8 | Compare models with appropriate metrics | ☐ | | | | |
| F9 | Error analysis | ☐ | | | | |
| F10 | Prevent data leakage | ◐ | Column roles (`ml/config.py`); `ColumnGuard`; patient-grouped split; all fitting inside one Pipeline on train only; leakage check in eda.md §8 | `tests/test_ml_preprocess.py` (forbidden columns rejected, train-only statistics, no refit on validation/test); test set scored once: Step 4 | | |
| F11 | Expose a versioned inference endpoint | ☐ | | | | |
| F12 | Show model output in the HealthTech dashboard | ☐ | | | | |

## Engineering constraints

| # | Requirement | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|
| E1 | Do not claim clinical validity or provide medical diagnosis | ☐ | | | | |
| E2 | Save preprocessing and model together in a reproducible pipeline | ◐ | `ml/preprocess.py` builds preprocessing as the first half of one `Pipeline` (saving: Step 6) | `test_engineering_learns_nothing_from_data` | | |
| E3 | Validate inference schema | ☐ | | | | |
| E4 | Handle malformed and out-of-range inputs | ☐ | | | | |
| E5 | Pin dependencies | ◐ | `backend/requirements.txt` (exact `==` for the ML stack) | version check comes with model loading (Step 6) | | |
| E6 | Record random seeds | ◐ | `ml/config.py` `SEED = 42`; dataset hash in DATA_CARD | `test_same_seed_gives_identical_data`, `test_different_seed_gives_different_data` (training seed: Step 4) | | |
| E7 | Document class imbalance | ☑ | DATA_CARD "Class imbalance" (16.4%) | `test_class_imbalance_is_in_the_documented_band` | | |
| E8 | Document dataset bias | ◐ | DATA_CARD "Bias" (age) | `test_age_bias_is_present` (per-group model errors: Step 5) | | |

## Acceptance checks

| # | Check | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|
| A1 | Training script can reproduce model artifact | ☐ | | | | |
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
