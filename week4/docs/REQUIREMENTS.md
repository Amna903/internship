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
- **Served model: still v1.0.0 (engineered logistic regression, C=0.1). Week 4 made no new release** (Step 4 decision, see Lessons). Its report (`release-1.0.0.md`) and files are rebuilt from Week 3's candidates and checked byte-for-byte; the dashboard's "About this model" panel names it, and a test pins that.
- **Clustering: real data plus a positive control** (user decision, Step 6). The main synthetic data has no patient habits (every engagement column is drawn independently per appointment), so Step 7 reports "no structure found" on it, compared with a shuffled baseline. A separate small control generator with 3–4 planted engagement habits (own module and seed, never touching `data.py`) tests whether the methods recover planted groups (adjusted Rand index). The dashboard's PCA plot and cluster descriptions use the control data, clearly labelled as such.
- **Test results so far are exploratory evidence** (mentor review on PR #1). Week 4's experimental selection never read the test set, but the release decision did, and the set had already been scored in Week 3. `metrics.md` §4 states both.
- **Fresh holdout reserved for the next final evaluation:** `backend/ml/holdout.py`, seed 20261101 (not 42), 2,000 patients, IDs offset by 10,000,000 so they cannot collide, fingerprint pinned. Never used for exploration, tuning, model choice or release selection; only that module may load it. Guarded by `tests/test_holdout.py`.
- **Champion/challenger rule: FROZEN on 2026-11-01** in `backend/ml/release_rule.py` (behaviour pinned by `tests/test_release_rule.py`). Changing it needs a new, dated decision recorded here before the evaluation it applies to. The rule:
  1. The served model is the champion. A challenger replaces it only if, on the same training folds, its mean CV PR-AUC beats the champion's by **more than one standard error** of the champion's mean.
  2. The simplicity preference applies **between model families with different explainability** (logistic regression before trees). Between equally explainable models (two logistic regressions), it doesn't apply: the higher CV mean wins.
  3. The challenger is decided on CV before the test set is scored. The test score is reported, not used to choose; if it ever argues against a CV decision, that is recorded as a finding, as in Step 4.
  4. Release numbering stays Week 3's: same inputs, retrained → minor version; inputs change → major version.

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
| S6 | Evaluate with confusion matrix | 4 | ☑ | [metrics.md](../backend/ml/reports/metrics.md) §4: one per algorithm, each at its own validation cut-off | `tests/test_ml_compare.py::test_each_algorithm_has_a_confusion_matrix_over_all_test_rows`, `::test_each_cut_off_is_the_models_own_validation_f1_best` | | |
| S7 | Evaluate with precision, recall, F1, ROC-AUC and PR-AUC | 4 | ☑ | [metrics.md](../backend/ml/reports/metrics.md) §4 (same table) | `tests/test_ml_compare.py::test_each_algorithm_has_a_confusion_matrix_over_all_test_rows` | | |
| S8 | Compare train versus validation performance | 2 | ☑ | [metrics.md § Train versus validation](../backend/ml/reports/metrics.md) (gap warning + out-of-bag) | `tests/test_ml_compare.py` (table, warning rule, memorising tree, out-of-bag) | | |
| S9 | Perform stratified cross-validation | 3 | ☑ | `ml/tune.py` (`StratifiedGroupKFold`, 5 folds, train rows only); [tuning.md §1–2](../backend/ml/reports/tuning.md) | `tests/test_ml_tune.py` (folds cover train once, no shared patients, stratified, train rows only) | | |
| S10 | Tune one model with GridSearchCV or RandomizedSearchCV | 3 | ☑ | `ml/tune.py` (`RandomizedSearchCV`, random forest, 30 seeded draws, one-standard-error rule); [tuning.md §3](../backend/ml/reports/tuning.md) | `tests/test_ml_tune.py` (seeded, matches manual CV, rule cases, committed choice follows the rule) | | |
| S11 | Explain feature importance or permutation importance | 5 | ☑ | [explain.md](../backend/ml/reports/explain.md) §1–2: permutation importance (served model), history pair shuffled as a group, random forest impurity vs permutation | `tests/test_ml_explain.py` (planted useless/perfect features, seeded, grouped shuffle, readings computed) | | |
| S12 | Inspect false positives/negatives | 5 | ☑ | [explain.md](../backend/ml/reports/explain.md) §3 (profiles, unavoidable vs model mistakes); most confident cases in [errors.md](../backend/ml/reports/errors.md) | `tests/test_ml_explain.py::test_profiles_add_up_to_the_validation_rows_and_match_the_error_counts` | | |
| S13 | Reproducible preprocessing pipeline for imputation, encoding and scaling | 4 | ☑ | `backend/ml/preprocess.py` inside every Pipeline; served `no-show-1.0.0.joblib` | `python -m ml.verify_release` (CI job), `tests/test_ml_artifact.py` | | |

## Unsupervised learning

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| U1 | Use non-sensitive profile/engagement features | 6 | ☑ | `backend/ml/cluster_features.py`, [cluster_features.md](../backend/ml/reports/cluster_features.md) §1–3: six per-patient engagement features; age, distance, history, outcome, reminder (clinic behaviour) and web share (redundant) excluded with reasons | `tests/test_cluster_features.py` (exclusions enforced, hand-made patient, one row per patient) | | |
| U2 | Run K-Means | 7 | ☑ | `backend/ml/cluster.py`; [clusters.md](../backend/ml/reports/clusters.md) §1–2 (real data and positive control) | `tests/test_ml_cluster.py` | | |
| U3 | Run one alternative (DBSCAN or Agglomerative Clustering) | 7 | ☑ | agglomerative (Ward) in `backend/ml/cluster.py`; [clusters.md](../backend/ml/reports/clusters.md) | `tests/test_ml_cluster.py` | | |
| U4 | Choose scaling | 6 | ☑ | [cluster_features.md](../backend/ml/reports/cluster_features.md) §4: rule fixed before clustering; RobustScaler chosen (lead-time outliers, max \|z\| 7.2; every IQR > 0) | `tests/test_cluster_features.py::test_scaling_rule_cases`, `::test_rule_picks_robust_scaling_for_these_patients` | | |
| U5 | Choose cluster count using silhouette score and/or elbow method | 7 | ☑ | silhouette rule (fewer clusters within 0.01), K-Means inertia (elbow) beside it; [clusters.md](../backend/ml/reports/clusters.md) | `tests/test_ml_cluster.py::test_k_rule_best_silhouette_and_fewer_clusters_on_a_tie`, `::test_chosen_k_follows_the_rule` | | |
| U6 | PCA for 2D visualization | 8 | ☑ | `backend/ml/cluster_view.py`; [cluster_view.md](../backend/ml/reports/cluster_view.md) §1 (variance kept: control 61%, real 49%); points in `cluster_view.json`, served by `GET /api/v1/clusters/` (drawn in the dashboard in Step 13) | `tests/test_ml_cluster_view.py`::test_pca_points_are_control_data_with_two_axes | | |
| U7 | Describe each cluster in neutral, non-clinical terms | 8 | ☑ | [cluster_view.md](../backend/ml/reports/cluster_view.md) §2 (control) and §3 (real-data clusters, marked misleading); built from the numbers | `tests/test_ml_cluster_view.py` (banned health/personal words, phrases match the numbers) | | |
| U8 | Compare methods | 7 | ☑ | [clusters.md](../backend/ml/reports/clusters.md): both methods on both datasets (silhouette, baseline verdict, ARI) | `tests/test_ml_cluster.py` | | |
| U9 | Explain why clusters are exploratory rather than ground-truth categories | 8 | ☑ | [cluster_view.md](../backend/ml/reports/cluster_view.md) §5 | `tests/test_ml_cluster_view.py`::test_report_explains_meaningful_vs_misleading_and_why_exploratory | | |

## LLM foundations and FAQ assistant

| # | Requirement (brief wording) | Step | Status | Code | Test | Demo | Me |
|---|---|---|---|---|---|---|---|
| L1 | Integrate one hosted or local LLM with a backend endpoint | 9 | ◐ | local Ollama (`llama3.2:3b`) behind `LLMClient` (`backend/assistant/llm.py`); `GET /api/v1/assistant/status/`; the question endpoint lands in Step 11 | `tests/test_assistant_foundation.py`::TestOllamaClient, ::TestStatusEndpoint | | |
| L2 | Define a system prompt | 9 | ☑ | `SYSTEM_PROMPT` in `backend/assistant/prompts.py` | `tests/test_assistant_foundation.py`::TestPrompt | | |
| L3 | Define a task-specific user prompt | 9 | ☑ | `USER_TEMPLATE`, passages in marked data blocks (`backend/assistant/prompts.py`) | `tests/test_assistant_foundation.py`::TestPrompt | | |
| L4 | Define a context window strategy | 9 | ☑ | `build_prompt`: fixed parts always in, ranked passages fill the rest, lowest dropped first; approximate token count with a 20% safety margin | `tests/test_assistant_foundation.py`::test_lowest_ranked_passages_are_dropped_first_when_the_budget_is_full | | |
| L5 | Define an output token limit | 9 | ☑ | `ASSISTANT_MAX_OUTPUT_TOKENS` = 512 (`config/settings.py`), sent as `num_predict`; cut-off output fails validation | `tests/test_assistant_foundation.py`::test_request_sends_schema_temperature_token_limit_and_context | | |
| L6 | Define a temperature | 9 | ☑ | 0.1, with the reason, in `config/settings.py` | `tests/test_assistant_foundation.py`::test_request_sends_schema_temperature_token_limit_and_context | | |
| L7 | Define a structured JSON response schema | 9 | ☑ | `ANSWER_SCHEMA` (`backend/assistant/schema.py`): answer, citations, refused; sent as Ollama's `format` and validated strictly; status decided by the server (`backend/assistant/verify.py`) | `tests/test_assistant_foundation.py`::TestValidation, ::TestStatus | | |
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
| C2 | Keep test data untouched until final evaluation | 4 | ◐ | Experimental selection did not read the test set (CV choice, validation confirmation, cut-offs). **Not complete:** the same test set was scored in Week 3, and in Week 4 it informed the release decision to keep v1.0.0, so it is no longer untouched. Fix: a fresh holdout is reserved for the next final evaluation (`backend/ml/holdout.py`); current test results are exploratory evidence | `tests/test_ml_compare.py::test_choice_cut_offs_and_rival_do_not_depend_on_test_labels` (selection), `tests/test_holdout.py` (reserved holdout) | | |
| C3 | Pin dependencies and random seeds | 0 | ◐ | `requirements.txt`, `ml/config.py` SEED | | | |
| C4 | Document provenance, bias, imbalance and limitations | 14 | ◐ | [DATA_CARD.md](DATA_CARD.md) | | | |
| C5 | Do not submit patient-identifiable data to external LLMs | 9 | ☑ | local model only; obvious identifiers redacted from questions before the prompt (`backend/assistant/privacy.py`); no profile or prediction data in the prompt | `tests/test_assistant_foundation.py`::TestPrivacy | | |
| C6 | Validate file types/sizes | 10 | ☐ | | | | |
| C7 | Enforce upload permissions | 10 | ☐ | | | | |
| C8 | Treat retrieved documents as untrusted | 11 | ☐ | | | | |
| C9 | Rate limits | 9 | ◐ | `assistant` scope, 10/min (status endpoint now; question endpoint in Step 11) | `tests/test_assistant_foundation.py`::test_rate_limited | | |
| C10 | Timeouts | 9 | ☑ | one deadline per answer (60 s, allows the measured ~6 s cold start); `manage.py warm_llm` | `tests/test_assistant_foundation.py`::test_slow_model_raises_timeout | | |
| C11 | Safe error responses | 9 | ◐ | timeout / unavailable / invalid_output statuses without details, reasons logged without the question (API mapping in Step 11) | `tests/test_assistant_foundation.py`::TestSafeErrors, ::test_the_question_text_is_never_logged | | |
| C12 | Approximate token/cost reporting | 9 | ☑ | server token counts per answer; local cost $0 and an illustrative hosted equivalent (`backend/assistant/costs.py`) | `tests/test_assistant_foundation.py`::test_cost_report_uses_server_token_counts_and_states_it_is_illustrative | | |
| C13 | Never present predictions or clusters as medical diagnoses | 8, 13 | ◐ | Week 3 wording + disclaimer | | | |

## Acceptance checks

| # | Requirement (brief wording) | Step | Status | Evidence | Me |
|---|---|---|---|---|---|
| A1 | Metrics comparison table for three supervised models | 4 | ☑ | [metrics.md](../backend/ml/reports/metrics.md) §1 (validation), §2 (CV), §4 (test) | |
| A2 | Confusion matrix | 4 | ☑ | [metrics.md](../backend/ml/reports/metrics.md) §4 | |
| A3 | One tuning experiment | 3 | ☑ | [tuning.md](../backend/ml/reports/tuning.md); regenerated by `python -m ml.verify_release` in CI | |
| A4 | Reproducible saved pipeline | 4 | ☑ | served `no-show-1.0.0` (kept; see Lessons), rebuilt byte-identically by `python -m ml.verify_release` in CI | |
| A5 | Two clustering algorithms | 7 | ☑ | [clusters.md](../backend/ml/reports/clusters.md) | |
| A6 | PCA plot | 8 | ◐ | data and report in [cluster_view.md](../backend/ml/reports/cluster_view.md) §1; the plot itself is drawn in the dashboard (Step 13) | |
| A7 | Cluster quality analysis | 7 | ☑ | [clusters.md](../backend/ml/reports/clusters.md): silhouette vs appointment-reshuffle baseline (no structure found on real data), false-pattern checks, ARI recovery on the positive control, stability | |
| A8 | Explanation of meaningful versus misleading clusters | 8 | ☑ | [cluster_view.md](../backend/ml/reports/cluster_view.md) §3–4 (real-data clusters as the concrete misleading example) | |
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
- **Step 3 (CI): one search setting sat on the one-standard-error bar.** On Linux, one of the 30 settings fell on the other side of the bar (bar 0.2664 vs 0.2666) without changing the choice. A known fragility: the check requires the choice to be identical, so a crossing that changed it would fail CI.
- **Step 4: the rule's choice was not shipped. Three things recorded honestly:**
  1. **The decision not to ship raw logistic regression was informed by the test result, so it is not test-independent.** On test, raw LR (the rule's choice) scored PR-AUC 0.267 against engineered LR's 0.280: −0.013, 95% interval [−0.026, −0.001]. The test set had also been scored once in Week 3 for v1.0.0, so it was never brand new for Week 4 (stated in `metrics.md` §4).
  2. **The CV-only argument also supports keeping v1.0.0 (champion/challenger).** The challenger (raw LR, CV mean 0.275) did not beat the champion (the served engineered LR, CV 0.283, one standard error 0.008), so there was no evidence to replace the served model.
  3. **Lesson: the simplicity preference made sense between logistic regression and trees, but between two logistic regressions both are equally explainable, so it only cost accuracy.** The champion/challenger rule above is now written down before any future evaluation.
- **Step 5: the caveat about correlated inputs worked the opposite way for the history pair.** Shuffled together, prior appointments and prior no-shows dropped PR-AUC by 0.039, less than the 0.060 sum of shuffling each alone. The engineered past no-show rate is built from both, so each single shuffle scrambles it and its importance is counted twice; shuffling prior no-shows alone also creates impossible rows (2.3%). Inputs can make single shuffles understate (when they cover for each other, shown by a test with two copies of one signal) or overstate (when they combine into one feature, as here). The report computes which case applies instead of assuming one.
- **Step 7: the real data has no clusters, and the positive control was only partially recovered.** Real data: both methods' silhouettes (K-Means 0.169, Ward 0.130) are below the 95th percentile of the appointment-reshuffle baseline (0.173, 0.163), so "no structure found", as the generator implies. Control: best ARI 0.52 ("partially recovered"), and the silhouette rule picked 3 and 2 groups, not the planted 4. The words for ARI (0.8 well, 0.5 partially, 0.2 weakly) **were set after seeing this result**, as the report says, and 0.52 sits just above the 0.5 threshold, so "partially" is borderline (the report computes and states this). A labelled diagnostic (not the result) shows what limits recovery: without the 'mixed' group ARI reaches 0.94, without `appointments` 0.64.
  - **Lesson: `appointments` both blurs real groups (control) and drives the false split on real data** (63% of the K-Means split's variance). It differs between patients by chance and counts as one sixth of every distance. A feature without engagement meaning should be questioned before clustering, not after.

