# Week 4 requirement → evidence checklist

Source: **"WEEK 4 | Supervised + Unsupervised ML and LLM Foundations"** in *Elevate Engine Weeks 4–6*. Each row is one line of that brief, worded as in the brief. Lines with several parts are split into one row per part, so none can be ticked half-done.

Fill in each row as the work is done:
- **Code:** where it's implemented.
- **Test:** the automated test that proves it, or "manual" plus what you checked.
- **Demo:** the Loom timestamp.
- **Me:** the date you re-ran the check yourself. Leave it blank until you have.

Status: ☐ not started · ◐ in progress · ☑ done and evidenced.

The Week 3 checklist is kept, finished, in [REQUIREMENTS-week3.md](REQUIREMENTS-week3.md).

## Decisions so far (Step 0)

- **Supervised task:** the same synthetic appointment no-show task as Week 3, extended rather than replaced. The brief says "expand the Week 3 ML system".
- **LLM:** local only, through **Ollama**. No data leaves the machine, so the rule against sending patient data to external LLMs holds by design. Tests and CI use a **fake LLM** behind the same interface.
- **Git:** all Week 4 work goes on the `week4` branch → a PR to `main` → reviewer **@ahmedhashir10**.
- **Model choice is by cross-validation (from Step 3 on).** See the lesson below. The rule is now fixed: no further rule changes.
- **Served model stays v1.0.0 until Step 4.** The release and its report (`release-1.0.0.md`) are rebuilt from Week 3's candidates, so it stays exactly reproducible; `metrics.md` compares every model on validation and scores no test rows until Step 4.

## Lessons recorded along the way

- **Step 2: the simplicity order ranked model families only, and CI exposed why that matters.** Two forests 0.0002 apart in validation PR-AUC swapped places between Mac (arm64) and Linux CI (x86): trees amplify last-digit floating-point differences into different splits, moving forest scores by about 0.001. So the chosen model depended on the machine. Fix: a within-family order (shallower trees, then larger leaves; on a remaining tie **more** trees, since tree count only steadies the vote and doesn't cause overfitting). The depth-6, leaf-50 forest now wins on both machines. This rule was written after seeing results, for the stability reason, and it changed the winner from the unlimited-depth forest (0.284) to depth 6 (0.281), within the tie margin. `metrics.md` is now checked for identical text and choice with numbers within 0.002; the release reports stay byte-exact.
- **Step 2: a multi-threaded random forest is not exactly reproducible.** Threads add the trees' outputs in varying order, changing the last digits, enough to flip a near-tie. Forests now run single-threaded; a test trains one twice and requires identical output.

## Supervised learning

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| S1 | Prepare a synthetic appointment-attendance dataset | 1 | ☑ | `backend/ml/data.py` (from Week 3); [SUPERVISED.md § Dataset](SUPERVISED.md#dataset-s1) | `tests/test_supervised_doc.py::test_dataset_section_states_the_real_size_and_seed` | | |
| S2 | Clearly define features, labels, split strategy and leakage checks | 1 | ☑ | [SUPERVISED.md](SUPERVISED.md) | `tests/test_supervised_doc.py` (every table checked against config and the data; history counts proven past-only) | | |
| S3 | Train Logistic Regression | 2 | ☑ | `ml/models.py` (raw + engineered, C grid) | `tests/test_ml_compare.py::test_logistic_regression_random_forest_and_gradient_boosting_are_all_trained` | | |
| S4 | Train Random Forest | 2 | ☑ | `ml/models.py` (`FOREST_GRID`, seeded, out-of-bag, single-threaded for exact reruns) | `tests/test_ml_compare.py::test_random_forest_*` | | |
| S5 | Train Gradient Boosting/XGBoost or SVM | 2 | ☑ | `ml/models.py` (HistGradientBoosting) | `tests/test_ml_compare.py::test_logistic_regression_random_forest_and_gradient_boosting_are_all_trained` | | |
| S6 | Evaluate with confusion matrix | 4 | ☐ | | | | |
| S7 | Evaluate with precision, recall, F1, ROC-AUC and PR-AUC | 4 | ☐ | | | | |
| S8 | Compare train versus validation performance | 2 | ☑ | [metrics.md § Train versus validation](../backend/ml/reports/metrics.md) (gap warning + out-of-bag) | `tests/test_ml_compare.py` (table, warning rule, memorising tree, out-of-bag) | | |
| S9 | Perform stratified cross-validation | 3 | ☑ | `ml/tune.py` (`StratifiedGroupKFold`, 5 folds, train rows only); [tuning.md §1–2](../backend/ml/reports/tuning.md) | `tests/test_ml_tune.py` (folds cover train once, no shared patients, stratified, train rows only) | | |
| S10 | Tune one model with GridSearchCV or RandomizedSearchCV | 3 | ☑ | `ml/tune.py` (`RandomizedSearchCV`, random forest, 30 seeded draws, one-standard-error rule); [tuning.md §3](../backend/ml/reports/tuning.md) | `tests/test_ml_tune.py` (seeded, matches manual CV, rule cases, committed choice follows the rule) | | |
| S11 | Explain feature importance or permutation importance | 5 | ☐ | | | | |
| S12 | Inspect false positives/negatives | 5 | ☐ | | | | |
| S13 | Reproducible preprocessing pipeline for imputation, encoding and scaling | 4 | ◐ | `backend/ml/preprocess.py` (from Week 3) | | | |

## Unsupervised learning

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| U1 | Use non-sensitive profile/engagement features | 6 | ☐ | | | | |
| U2 | Run K-Means | 7 | ☐ | | | | |
| U3 | Run one alternative (DBSCAN or Agglomerative Clustering) | 7 | ☐ | | | | |
| U4 | Choose scaling | 6 | ☐ | | | | |
| U5 | Choose cluster count using silhouette score and/or elbow method | 7 | ☐ | | | | |
| U6 | PCA for 2D visualization | 8 | ☐ | | | | |
| U7 | Describe each cluster in neutral, non-clinical terms | 8 | ☐ | | | | |
| U8 | Compare methods | 7 | ☐ | | | | |
| U9 | Explain why clusters are exploratory rather than ground-truth categories | 8 | ☐ | | | | |

## LLM foundations and FAQ assistant

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| L1 | Integrate one hosted or local LLM with a backend endpoint | 9 | ☐ | | | | |
| L2 | Define a system prompt | 9 | ☐ | | | | |
| L3 | Define a task-specific user prompt | 9 | ☐ | | | | |
| L4 | Define a context window strategy | 9 | ☐ | | | | |
| L5 | Define an output token limit | 9 | ☐ | | | | |
| L6 | Define a temperature | 9 | ☐ | | | | |
| L7 | Define a structured JSON response schema | 9 | ☐ | | | | |
| L8 | Educational FAQ assistant over approved fictional clinic policies | 10 | ☐ | | | | |
| L9 | Document upload | 10 | ☐ | | | | |
| L10 | Text extraction | 10 | ☐ | | | | |
| L11 | Chunking | 10 | ☐ | | | | |
| L12 | Embeddings | 10 | ☐ | | | | |
| L13 | Vector search | 10 | ☐ | | | | |
| L14 | Cited source passages | 11 | ☐ | | | | |
| L15 | Explicit "insufficient information" behavior | 11 | ☐ | | | | |

## Dashboard

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| D1 | Separate tab for supervised predictions | 13 | ◐ | `frontend/app/admin/predictions/` (from Week 3) | | | |
| D2 | Separate tab for unsupervised cluster visualizations | 13 | ☐ | | | | |
| D3 | Separate tab for LLM Q&A | 13 | ☐ | | | | |
| D4 | Display model versions, metrics and educational-use disclaimers | 13 | ☐ | | | | |

## LLM evaluation

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| E1 | At least 12 LLM evaluation prompts | 12 | ☐ | | | | |
| E2 | Covering answerable, ambiguous, out-of-scope and prompt-injection attempts | 12 | ☐ | | | | |
| E3 | Compare two prompts or retrieval settings | 12 | ☐ | | | | |
| E4 | Record citation quality and failures | 12 | ☐ | | | | |

## Engineering constraints

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| C1 | Train-only fitting for preprocessing and tuning | 3 | ☑ | Pipeline fitted inside each fold; folds and search see the train part only | `tests/test_ml_tune.py::test_tuning_only_ever_sees_training_rows` | | |
| C2 | Keep test data untouched until final evaluation | 4 | ◐ | Week 3 `evaluate_on_test` | | | |
| C3 | Pin dependencies and random seeds | 0 | ◐ | `requirements.txt`, `ml/config.py` SEED | | | |
| C4 | Document provenance, bias, imbalance and limitations | 14 | ◐ | [DATA_CARD.md](DATA_CARD.md) | | | |
| C5 | Do not submit patient-identifiable data to external LLMs | 9 | ☐ | | | | |
| C6 | Validate file types/sizes | 10 | ☐ | | | | |
| C7 | Enforce upload permissions | 10 | ☐ | | | | |
| C8 | Treat retrieved documents as untrusted | 11 | ☐ | | | | |
| C9 | Rate limits | 9 | ☐ | | | | |
| C10 | Timeouts | 9 | ☐ | | | | |
| C11 | Safe error responses | 9 | ☐ | | | | |
| C12 | Approximate token/cost reporting | 9 | ☐ | | | | |
| C13 | Never present predictions or clusters as medical diagnoses | 8, 13 | ◐ | Week 3 wording + disclaimer | | | |

## Acceptance checks

| # | Requirement (brief wording) | Step | Status | Evidence | Me |
|---|---|---|---|---|---|
| A1 | Metrics comparison table for three supervised models | 4 | ☐ | | |
| A2 | Confusion matrix | 4 | ☐ | | |
| A3 | One tuning experiment | 3 | ☑ | [tuning.md](../backend/ml/reports/tuning.md); regenerated by `python -m ml.verify_release` in CI | |
| A4 | Reproducible saved pipeline | 4 | ☐ | | |
| A5 | Two clustering algorithms | 7 | ☐ | | |
| A6 | PCA plot | 8 | ☐ | | |
| A7 | Cluster quality analysis | 7 | ☐ | | |
| A8 | Explanation of meaningful versus misleading clusters | 8 | ☐ | | |
| A9 | LLM answers cite relevant approved documents | 11 | ☐ | | |
| A10 | Reject unsupported claims | 11 | ☐ | | |
| A11 | Survive at least two adversarial prompt tests | 12 | ☐ | | |
| A12 | API requests/responses for prediction, clustering and LLM endpoints | 14 | ☐ | | |
| A13 | Document the 12-case evaluation results | 12 | ☐ | | |

## Required submission

| # | Requirement (brief wording) | Step | Status | Evidence | Me |
|---|---|---|---|---|---|
| R1 | GitHub repository with meaningful commits | all | ◐ | `week4` branch | |
| R2 | Setup and run/test commands | 14 | ☐ | | |
| R3 | README architecture decisions, limitations, screenshots and API examples | 14 | ☐ | | |
| R4 | Loom: working demo, code architecture, actual AI prompts and refinements, context management, blast-radius controls, debugging and verification | 14 | ☐ | | |
| R5 | Post repository and Loom links in the team channel | 14 | ☐ | | |
| R6 | Keep all previous features working and provide regression-test evidence | 0, 14 | ◐ | Week 1–3 suites green in CI | |
| R7 | Git workflow: branch, PR, reviewer @ahmedhashir10 (mentor instruction) | 0, 14 | ◐ | `week4` branch | |
- **Step 3: the model-choice rule changed after seeing results. This was the question Step 3 set out to answer.** Step 3 asked whether Step 2's validation differences were bigger than chance. Five patient-grouped, stratified folds of the training rows answered no: the random forest's validation lead over engineered logistic regression (0.284 vs 0.276) reversed in cross-validation (0.269 vs 0.283; logistic regression ahead in all 5 folds). **One validation draw (~4,000 rows) was too noisy to choose between close models.** So, with the user's approval, the rule changed from "highest validation PR-AUC" to **cross-validation with the one-standard-error rule and the simplicity order**, with validation kept as a confirmation check (within CV mean ± 2 fold SDs) and for the decision cut-off. The test set was still untouched when this was decided. **No more rule changes after this.**
  - What the new rule picked: **raw logistic regression (C=10)**. Its CV mean (0.2751) is 0.0003 above the one-standard-error bar (0.2748). Engineered features lead by 0.008 on average across folds, but with a fold-to-fold spread of 0.009 (ahead in 4 of 5 folds), so the gain is within the noise and the simpler model wins the tie. This is recorded as a finding, not adjusted. Week 3's test set showed engineered ahead (+0.013), but test results may not be used for choosing.
  - The tuned forest (depth 4, leaf 50, 33% of columns per split, 300 trees) reached CV 0.268 ± 0.017: tuning did not lift forests to logistic regression's level.
  - The release version is decided in Step 4, from what the brief requires.

