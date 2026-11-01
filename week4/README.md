# HealthProfile: Week 4 (supervised + unsupervised ML and a local LLM assistant)

> **Educational prototype on synthetic, fictional data.** Predictions, clusters and assistant answers
> are never a medical assessment, diagnosis or advice. The assistant answers only from approved,
> fictional clinic policies, and runs on a local model: no data leaves the machine.

Week 4 extends the Week 3 system:
- the supervised comparison now covers three algorithm families, chosen by cross-validation;
- exploratory clustering, with a positive control;
- a retrieval-based policy assistant whose answers are verified by the server;
- three dashboard tabs.

Everything from Weeks 1–3 further down still works, and the tests confirm it ([regression evidence](docs/regression.md)).

![Clusters tab: PCA plot of the labelled control data, real-data verdict and method comparison](docs/screenshots/w4-02-clusters-tab.png)

![Assistant tab: an answer with a server-checked citation, tokens and cost](docs/screenshots/w4-03-assistant-answered.png)

## Week 4 checklist

Each row is one part of the Week 4 brief. The full table, with test names and a column for checks I
re-ran myself, is in [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).

| Brief requirement | Where it is built | Proof |
|---|---|---|
| Logistic regression, random forest, gradient boosting | `backend/ml/models.py` | `tests/test_ml_compare.py` |
| Confusion matrix, precision, recall, F1, ROC-AUC, PR-AUC; train vs validation | [metrics.md](backend/ml/reports/metrics.md) §1, §4 | `tests/test_ml_compare.py` |
| Stratified CV and one tuning experiment | `ml/tune.py`: patient-grouped stratified 5-fold CV, `RandomizedSearchCV` → [tuning.md](backend/ml/reports/tuning.md) | `tests/test_ml_tune.py` |
| Feature importance and error inspection | permutation importance, false positive/negative profiles → [explain.md](backend/ml/reports/explain.md) | `tests/test_ml_explain.py` |
| K-Means plus one alternative, on non-sensitive features | K-Means and Ward → [clusters.md](backend/ml/reports/clusters.md); features → [cluster_features.md](backend/ml/reports/cluster_features.md) | `tests/test_ml_cluster.py`, `tests/test_cluster_features.py` |
| PCA plot, cluster quality, meaningful vs misleading clusters | Clusters tab; [cluster_view.md](backend/ml/reports/cluster_view.md) | `tests/test_clusters_api.py`, `e2e/run_week4_e2e.py` |
| Local LLM; approved documents only; citations | Ollama `llama3.2:3b`; `backend/assistant/` | `tests/test_assistant_*.py` |
| Upload validation, approval before search | `assistant/uploads.py`, documents API | `tests/test_assistant_documents.py` |
| Reject unsupported claims; survive adversarial prompts | server-side checks (`assistant/verify.py`); red-team diagnostic | `tests/test_assistant_ask.py`, [eval_report.md](backend/assistant/eval/eval_report.md) |
| 12+ evaluation cases; compare two settings; citation quality and failures | 18 frozen cases, settings A and B → [eval_report.md](backend/assistant/eval/eval_report.md), [known_gaps.md](backend/assistant/eval/known_gaps.md) | `tests/test_assistant_evaluate.py`, `tests/test_eval_freeze.py` |
| Dashboard tabs with versions, metrics, disclaimers | `/admin/predictions`, `/admin/clusters`, `/admin/assistant` | `e2e/run_week4_e2e.py` (23 checks) |
| API examples | [docs/API.md](docs/API.md), Week 4 section, captured from the running server | |

## Results

**Supervised (synthetic data, so these numbers show how well a model recovers the generating formula).**
- **Served model: still `no-show-1.0.0`** (engineered logistic regression, C=0.1): test PR-AUC 0.280,
  ROC-AUC 0.663, against a floor of 0.164 and an oracle ceiling of 0.321.
- The Week 4 rule chose by cross-validation with the one-standard-error rule, and its choice
  (`logreg_raw`, CV PR-AUC 0.275) was **not shipped**: on the same folds it did not beat the served
  model (0.283) by more than one standard error (0.008). See [metrics.md](backend/ml/reports/metrics.md) §2 and §7.
- **These test results are exploratory evidence.** The same test set was scored in Week 3, and in Week 4
  it informed the release decision. A fresh holdout is reserved for the next final evaluation (see
  "Mentor review" below).

**Clustering.**
- On the real synthetic patients, **no structure was found**. Neither method's separation score beat
  the score on shuffled data (K-Means 0.169 vs 0.173; Ward 0.130 vs 0.163). The clusters K-Means forms
  anyway are shown on the dashboard as a misleading example.
- On a positive control with planted habits, K-Means **partly** recovered them (ARI 0.52; Ward 0.18 at its chosen k).

**Assistant ([eval_report.md](backend/assistant/eval/eval_report.md)).**
- **17 of 18 frozen cases passed** with the shipped settings and also with the comparison setting. The
  only failure is A6, a paraphrased answerable question below the similarity floor.
- 17 verified citations, 0 rejected.
- **Honest caveat:** 10 of the 12 cases that shouldn't be answered were stopped by the similarity floor,
  before the model. So the frozen set doesn't test the model's injection resistance.
- A **red-team set** added after the evaluation, diagnostic only, does test it. Five attacks wrapped in
  on-topic questions (R1, R2, R3, R4, R6) cleared the floor and reached the model, and **none leaked**.
- With the floor turned off, 13 of 18 passed. Nothing leaked, but some answers were true and off-topic.
  The gaps are listed in [known_gaps.md](backend/assistant/eval/known_gaps.md).

## Architecture and decisions

```
Next.js admin tabs ──► Django REST (admin session, CSRF, rate limits, audit)
  Predictions  ──► /api/v1/predictions/no-show/ ──► saved scikit-learn Pipeline (SHA-256 checked)
  Clusters     ──► /api/v1/clusters/            ──► committed results (no clustering per request)
  Assistant    ──► /api/v1/assistant/ask/       ──► medical check ─► vector search (floor) ─► Ollama ─► server checks
```

- **Choose by cross-validation, release by champion/challenger.** In Step 3, one validation draw was too
  noisy to separate close models, so model choice moved to patient-grouped CV with the
  one-standard-error rule. A challenger replaces the served model only if it wins by more than one
  standard error on the same folds. That rule is frozen in `ml/release_rule.py`.
- **The server decides the assistant's status, not the model.** The 3B model labelled correct answers
  "insufficient information" (Step 9), so the model now returns only `answer`, `citations` and
  `refused`. The server shows an answer only if all of these hold:
  - each citation points to a passage the model was given;
  - each quote is in that passage;
  - every number in the answer is in the quotes;
  - the answer has at least two key terms;
  - the polarity check passes in both directions;
  - word-overlap groundedness reaches the tuned threshold;
  - the answer doesn't repeat the system prompt.
- **Layered defences, in a fixed order:**
  1. medical questions are refused before retrieval;
  2. retrieval below the similarity floor returns "insufficient information" without a model call;
  3. the server checks the model's reply.

  Uploads arrive **pending** and are searchable only after an admin approves them. Each vector stores
  the embedder that made it: vectors from another embedder are skipped and reported, and re-indexing
  happens only through an admin command.
- **Dev set versus frozen evaluation.** The floor, top-k and groundedness threshold were tuned on 11
  development questions only. The 18 evaluation cases (12 written by me) were frozen, with SHA-256
  pinned, before tuning. Settings A and B were named before the evaluation ran, and A shipped whatever
  B scored.
- **Local model only.** Ollama runs `llama3.2:3b` and `nomic-embed-text`, so no data leaves the
  machine. Tests and CI use a fake model and fake embedder behind the same interface.
- **Weekly folders: a trade-off to fix.** Each week lives in its own folder (`week1/` … `week4/`),
  started as a full copy of the previous week. That kept each review separate, but it duplicates code,
  and the brief says to *extend the same HealthTech application*, with Week 6 integrating into one
  application. **Plan:** move to a single codebase, marking each week's state with a git tag (for
  example `week4-final`) instead of a copied folder.

## Mentor review on PR #1: how each point was addressed

1. **One consistent account of the test set.** *Experimental selection* used CV on training rows,
   confirmed on validation, and never read the test set. A test flips every test label and checks the
   choice doesn't change. The *release decision* to keep v1.0.0 was made after reading test results.
   `metrics.md` states both, and C2 in the checklist is ◐ (in progress) for that reason.
2. **A fresh holdout that has never been opened.** `backend/ml/holdout.py` has a seed of 20261101 (not
   42) and 2,000 patients, with IDs offset so they can't collide with the main data, and its fingerprint
   is pinned. `tests/test_holdout.py` guards it: no other module may import or load it, and no copy of
   its rows is committed. Nothing has read its labels. The champion/challenger rule was frozen before
   any future evaluation.
3. **Draft until the evidence is in.** The PR stayed a draft through Steps 5–14. Each step was ticked
   in the PR checklist only after CI was green, with links to its code, report and tests.

## Run and test

Prerequisites: Python 3.14 and Node 20 (the versions CI uses), and [Ollama](https://ollama.com) for the assistant.

```bash
# Local model (once)
ollama pull llama3.2:3b && ollama pull nomic-embed-text

# Backend
cd week4/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_env.py            # writes .env with generated secrets
python manage.py migrate
python manage.py seed_demo            # synthetic admin and member accounts
python manage.py load_policies --admin admin@example.test   # the fictional clinic policies, approved and indexed
python manage.py warm_llm             # loads the model so the first question isn't slow
python manage.py runserver

# Frontend (second terminal)
cd week4/frontend && npm ci && npm run dev    # http://localhost:3000/admin/login
```

| What | Command (from `week4/backend` unless noted) |
|---|---|
| Backend tests (fake model, no Ollama needed) | `python -m pytest -q` |
| Model release check (rebuilds v1.0.0 byte for byte) | `python -m ml.verify_release` |
| Assistant evaluation (real model, about 15 minutes) | `python manage.py evaluate_assistant --admin admin@example.test` |
| Re-index after changing the embedder | `python manage.py reindex_documents --admin admin@example.test` |
| Frontend tests, typecheck, build | `cd week4/frontend && npm test && npx tsc --noEmit && npm run build` |
| Browser check, Week 4 tabs (needs both servers, Ollama, `pip install playwright`) | `python ../e2e/run_week4_e2e.py <admin_password> <screenshots_dir>` |
| Browser check, Week 3 page | `python ../e2e/run_week3_e2e.py <admin_password> <member_password> <screenshots_dir>` |

If port 3000 is taken, run the frontend on another port and set `E2E_BASE=http://127.0.0.1:<port>`.
Add that origin to `CSRF_TRUSTED_ORIGINS` for the backend. The assistant allows 10 questions a minute,
so wait a minute between browser runs.

CI (`.github/workflows/ci.yml`) runs on every push:
- the backend suites on PostgreSQL 16 and SQLite;
- the frontend checks;
- `python -m ml.verify_release`.

## Limitations

- **Synthetic data throughout.** The scores show how well models recover a known formula, not real
  clinic behaviour. See the [data card](docs/DATA_CARD.md).
- **The test set has been reused**, so the supervised test numbers are exploratory. The reserved holdout
  is for the next final evaluation.
- **The real data has no clusters to find.** The engagement columns are drawn independently, so the
  dashboard's PCA picture uses labelled control data.
- **The assistant's checks compare words, not meaning.** Relevance currently relies on the similarity
  floor. Known gaps are listed, without fixes applied on eval results, in
  [known_gaps.md](backend/assistant/eval/known_gaps.md):
  - true but off-topic answers when the floor is off;
  - a terse answer to an ambiguous question;
  - a false polarity block on a paraphrase;
  - meaning-level negation flips.
- **The evaluation is small.** With 18 cases, a 1–2 case difference is noise. The red-team set was
  written after the evaluation and is diagnostic only.
- **A 3B local model** is slow on a laptop (several seconds per answer) and its answers vary between
  runs, hence the three seeds and the two-of-three majority.
- **Not all versions are pinned.** The ML libraries are pinned exactly, but the web-framework
  dependencies from Week 1 use version ranges, and the Ollama model tags aren't pinned to a digest.
- **Code is duplicated across weekly folders** (see the decision above).

---

# HealthProfile: Week 3 (machine-learning pipeline and prediction API)

> **Educational prototype on synthetic data.** It estimates whether a *fictional* appointment may be
> missed, to help decide on an extra reminder. It is not a medical assessment, makes no diagnosis and
> has no clinical validity.

Week 3 adds a reproducible scikit-learn pipeline, trained on a seeded synthetic dataset and served by a
versioned, admin-only API, with its output shown in the admin dashboard. It builds on Week 2 (copied
into this folder with all its review fixes). Every Week 1 and Week 2 feature further down still works,
and the tests confirm it.

![No-show estimate in the admin dashboard](docs/screenshots/w3-01-estimate-extra-reminder.png)

## Week 3 checklist

Each row is one line of the Week 3 brief. The full table, with every test name and a column for checks
I re-ran myself, is in [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).

| Brief requirement | Where it is built | Proof |
|---|---|---|
| Synthetic data; provenance, licence, schema, limitations | `backend/ml/data.py` (seed 42) · [DATA_CARD](docs/DATA_CARD.md) | `tests/test_ml_data.py` |
| Exploratory analysis | `ml/eda.py` → [eda.md](backend/ml/reports/eda.md) | `tests/test_ml_eda.py` |
| Missing-value handling | median imputation learned from training rows only, plus a "was missing" flag (`ml/preprocess.py`) | `tests/test_ml_preprocess.py` |
| Train / validation / test split | 60/20/20, grouped by patient (`ml/split.py`) | no patient in two parts (test) |
| Baseline + improved scikit-learn models | floor → logistic regression (baseline) → logistic regression + engineered features, and gradient boosting (`ml/models.py`) | `tests/test_ml_train.py` |
| Appropriate metrics and error analysis | PR-AUC, ROC-AUC, Brier, oracle ceiling, bootstrap interval → [metrics.md](backend/ml/reports/metrics.md); per-group errors, calibration, bias → [errors.md](backend/ml/reports/errors.md) | `tests/test_ml_train.py`, `tests/test_ml_errors.py` |
| No data leakage | column guard, patient-grouped split, training-only fitting, choices on validation only, test set scored once | leakage tests in `test_ml_preprocess.py` and `test_ml_train.py` |
| Versioned inference endpoint | `POST /api/v1/predictions/no-show/`, `GET /api/v1/models/no-show/` | `tests/test_predictions_api.py` |
| Output shown in the dashboard | `/admin/predictions` | unit, contract and real-browser tests |
| No clinical claims | disclaimer beside every result; plain wording ("Extra reminder suggested", never "high risk") | wording tests in backend, frontend and browser |
| Preprocessing + model saved together, reproducibly | one Pipeline in `ml/artifacts/no-show-1.0.0.joblib` + `.json` metadata | `tests/test_ml_artifact.py` |
| Validated schema; malformed and out-of-range input | strict serializer generated from one shared schema | 68 API tests |
| Pinned dependencies, recorded seeds, imbalance and bias documented | exact `==` pins · `SEED = 42` · [DATA_CARD](docs/DATA_CARD.md) | pins checked against the model's metadata |
| **Acceptance:** training reproduces the model file | `python -m ml.artifact` | rebuilt in a fresh process: same data, metrics and predictions; byte-identical on the building platform |
| **Acceptance:** API returns validated output and model version | see the sample below | `test_returns_model_version_prediction_and_disclaimer` |
| **Acceptance:** README has metrics, limitations, sample request/response | the next three sections | `tests/test_docs.py` checks the numbers here match the generated reports |

## Metrics (test set, scored once, after every choice)

Synthetic data: these numbers show how well a model recovers the formula that generated the data. They
say nothing about real clinics. The test set holds 3,952 appointments of 1,000 patients who were never in
training. 16.5% of them are no-shows.

| model | PR-AUC ↑ | ROC-AUC ↑ | Brier ↓ | gap closed (floor → oracle) |
|---|---|---|---|---|
| Floor: always predicts the average | 0.164 | 0.500 | 0.1374 | 0% |
| Baseline: logistic regression, raw inputs | 0.267 | 0.649 | 0.1320 | 66% |
| Gradient boosting + engineered features | 0.268 | 0.662 | 0.1315 | 66% |
| **Served: logistic regression + engineered features** | **0.280** | **0.663** | **0.1307** | **74%** |
| Oracle ceiling: the generator's true probability | 0.321 | 0.714 | 0.1264 | 100% |

- **Main metric: PR-AUC.** No-shows are the 16% minority, so accuracy would mislead: always saying
  "attends" scores 84% and is useless.
- **Is the improvement real?** Served minus baseline, test PR-AUC: **+0.013**, 95% interval
  **[+0.001, +0.025]** (bootstrap over whole patients). Real, but small.
- **Decision cut-off: 16.9%**, chosen on validation (F1). On the test set the model flags 39.9% of
  appointments for an extra reminder. It catches **59.7%** of the no-shows, and **24.6%** of the flagged
  appointments really are no-shows (against 16.5% by chance). That is acceptable only because the
  action is cheap: one extra message.
- **Calibration:** expected calibration error 1.41 points, and no bin outside the sampling-noise limit,
  so no recalibration.
- **Every planted direction was learned:** longer lead time ↑, reminder ↓, younger ↑, telehealth ↓,
  distance ↑, past no-shows ↑ ([errors.md §6](backend/ml/reports/errors.md)).

Full tables: [metrics.md](backend/ml/reports/metrics.md) · [errors.md](backend/ml/reports/errors.md).

## Dataset limitations (short version; full list in the [data card](docs/DATA_CARD.md))

- **Synthetic only.** The model can only learn effects that were planted, and the effect sizes are
  invented.
- **Age bias, planted and measured.** On validation, 71.8% of 18–24-year-olds who attended were flagged,
  against 24.0% of 55–64-year-olds. Removing age was analysed (PR-AUC 0.276 → 0.260) but not shipped,
  because the test set had already been used. The output may only drive supportive actions (an extra
  reminder), never refusals, penalties or priority.
- **Class imbalance:** 16.4% no-shows.
- **Missing values are completely random** (7.7% of distances). In real data, a missing value often
  means something.
- **No time dimension:** no dates, seasons or trends, and the split is not by time.
- About two-thirds of errors (66.5% on validation) would happen **even with perfect knowledge** of the true probability, because
  each outcome is a weighted coin flip.

## Sample request and response

The caller supplies the appointment history counts; the API does not look them up. It requires an admin
session, the CSRF token and at most 60 requests a minute. Every estimate is audited with the model
version, never the inputs.

```bash
cd backend
rm -f jar.txt
curl -s -c jar.txt -b jar.txt http://127.0.0.1:8000/api/auth/csrf/ > /dev/null
CSRF=$(grep csrftoken jar.txt | awk '{print $7}')
curl -s -c jar.txt -b jar.txt -H "X-CSRFToken: $CSRF" -H "Content-Type: application/json" -d '{"email":"admin@example.test","password":"YOUR_ADMIN_PASSWORD"}' http://127.0.0.1:8000/api/admin/login/
CSRF=$(grep csrftoken jar.txt | awk '{print $7}')
curl -s -b jar.txt -H "X-CSRFToken: $CSRF" -H "Content-Type: application/json" -d '{"lead_time_days":14,"appointment_weekday":"tuesday","appointment_hour":10,"age_band":"35-44","visit_type":"in_person","booking_channel":"web","reminder_sent":true,"prior_appointments":4,"prior_no_shows":0,"distance_km":6.5}' http://127.0.0.1:8000/api/v1/predictions/no-show/
```

`200`
```json
{"model_version": "no-show-1.0.0",
 "prediction": {"no_show_probability": 0.1279, "suggested_action": "standard_reminder",
                "suggested_action_label": "Standard reminder", "decision_threshold": 0.1688,
                "average_no_show_rate": 0.1645},
 "disclaimer": "Educational prototype trained on synthetic data. Estimates whether a fictional appointment may be missed, to help plan reminders. Not a medical assessment and not clinically validated."}
```

Errors use the same envelope as the rest of the API:
- an unknown field, a wrong type or an out-of-range value gives `400 validation_error`, with every
  problem listed in one response, e.g. `{"appointment_hour": ["Ensure this value is less than or equal to 19."]}`;
- more no-shows than appointments gives `400` on `prior_no_shows`;
- broken JSON gives `400 parse_error`, and a body over 4 KB gives `413`;
- no admin session (including a member's token) gives `401`; no CSRF token gives `403`; too many
  requests give `429`;
- a missing, corrupted or mismatched model file gives `503 model_unavailable`.

Every input and every error: [docs/API.md](docs/API.md#week-3-no-show-estimate-api-admin-only).

## Architecture and decisions

```
ml/data.py ─▶ ml/eda.py ─▶ ml/split.py ─▶ ml/preprocess.py + ml/features.py ─▶ ml/train.py ─▶ ml/errors.py
 seeded         report       60/20/20 by     one Pipeline: guard, engineered       compare on      error analysis
 generator      (eda.md)     patient         features, impute, scale, one-hot      validation,     (errors.md)
                                                                                   test once
                                                                                       │
                                                       ml/artifact.py ◀────────────────┘
                                                       no-show-1.0.0.joblib + .json (SHA-256, versions)
                                                              │  ml/inference.py: verify, then load once
                                                              ▼
       Next.js /admin/predictions ──proxy──▶ Django /api/v1/predictions/no-show/ (admin session, CSRF,
       (form, examples, result + disclaimer)            rate limit, strict schema, audit) ──▶ model
```

| Decision | Why | Rejected alternative |
|---|---|---|
| Seeded synthetic generator with a known formula | No privacy or licence risk; reproducible; the true probability gives an **oracle ceiling** and lets us check what the model learned | A public dataset (needs explicit approval, real records); data made by an LLM (not reproducible) |
| A curve, an interaction and a hidden habit in the formula | Gives an improved model something real to find, so the comparison means something | A purely linear formula (the baseline would already be perfect) |
| Split by patient | The same person in train and test would let the model "recognise" people | A random row split |
| All preprocessing inside one Pipeline, fitted on training rows | Nothing learned from validation or test; saved together with the model | Preprocessing the whole dataset up front |
| PR-AUC + Brier, with the cut-off chosen on validation | Imbalance; honest probabilities | Accuracy; a fixed 0.5 cut-off |
| No class weighting | It inflates every probability ("16% means 16%" would break) | `class_weight="balanced"` |
| Logistic regression chosen over gradient boosting | Higher validation PR-AUC, and simpler models win near-ties by a rule written before training: explainable | Picking the fanciest model |
| Test set touched once; no changes after it | Otherwise its score is optimistic | Recalibrating or dropping age afterwards (reported as next steps instead) |
| One `.joblib` + timestamp-free `.json` with SHA-256 and exact versions | Reproducible rebuilds; loading refuses corrupted or mismatched files | ONNX (awkward with custom transformers); unversioned pickles |
| API inside the existing Django app | Reuses the Week 2 admin session, CSRF, throttling, audit and error format | A separate FastAPI service (a second auth system) |
| `/api/v1/` plus `model_version` in every response | Separates the API contract from the model behind it | Model version only in the URL |
| Plain wording, neutral colours, disclaimer beside the result | No clinical claims | "High risk" labels |
| Per-age-group thresholds | (rejected) | They would deliberately treat people differently by age |

Design notes per step: [docs/WEEK3.md](docs/WEEK3.md).

## Run and test

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/init_env.py
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000/admin/login and sign in as `admin@example.test`. The password is printed by
`init_env.py` and stored in `backend/.env`. Then click **No-show estimate**.

The ML pipeline, step by step. Each command is deterministic and writes the committed file shown; the
model file is already committed, so this is only needed to rebuild:

```bash
cd backend
python -m ml.data
python -m ml.eda
python -m ml.split
python -m ml.train
python -m ml.errors
python -m ml.artifact
```

| Command | Writes |
|---|---|
| `python -m ml.data` | `ml/data/appointments.csv` (git-ignored, rebuilt identically) |
| `python -m ml.eda` | `ml/reports/eda.md` |
| `python -m ml.split` | prints the split summary |
| `python -m ml.train` | `ml/reports/metrics.md` |
| `python -m ml.errors` | `ml/reports/errors.md` |
| `python -m ml.artifact` | `ml/artifacts/no-show-1.0.0.joblib` + `.json` |

Tests:

```bash
cd backend
python -m pytest
cd ../frontend
npm test
npm run typecheck
npm run build
```

**Check that everything reproduces** (acceptance check A1, about 25 seconds):

```bash
cd backend
python -m ml.verify_release
```

It rebuilds the dataset, the three reports and the model from scratch and compares them with the
committed files, level by level. It prints `PASS` / `SKIP` / `FAIL` for each and exits non-zero on any
mismatch.

**Who ran what.** CI (`.github/workflows/ci.yml`) runs the backend suite on PostgreSQL 16 and SQLite,
the frontend typecheck, tests and build, and a separate **"ML reproducibility (week3)"** job that runs
`python -m ml.verify_release` on Linux, all on every push. The real-browser check
(`e2e/run_week3_e2e.py`, 17 checks) needs both servers running, so it is not in CI. It was run locally
on 2026-10-27: 17/17. To run it you need `pip install playwright` and
`python -m playwright install chromium`, then:

```bash
python e2e/run_week3_e2e.py "<admin password>" "<member password>" docs/screenshots
```

## Model release and safe loading

`backend/ml/artifacts/no-show-1.0.0.joblib` holds the whole Pipeline: the input guard, the engineered
features, preprocessing and the logistic regression. `no-show-1.0.0.json` next to it records:
- the seed and the dataset SHA-256
- the feature schema
- the decision cut-off
- the metrics
- the exact library versions
- the file's SHA-256

It has no timestamp, so rebuilds are identical. Both files are committed.

| Reproducibility level | What matches | Where |
|---|---|---|
| 1 | Dataset SHA-256 | everywhere |
| 2 | Metrics and cut-off in the metadata | everywhere (CI checks on Linux) |
| 3 | Predicted probabilities, within 1e-9 | everywhere |
| 4 | The `.joblib` file, byte for byte | same platform and library versions as the committed build (macOS arm64). Floating-point results can differ in the last bits across CPUs. |

**Safe loading** (`ml/inference.py`). The file is opened only after all of these checks pass:
- both files exist;
- the metadata names this version and our exact feature schema;
- the installed scikit-learn is the exact version the model was saved with;
- the file's SHA-256 matches.

Any failure becomes `ModelUnavailable`, which the API returns as `503`. The SHA-256 check catches
accidental corruption or mismatched files. It is not protection against a deliberate attacker, because
the fingerprint is stored in the `.json` next to the file. Real protection comes from only loading our
own committed file, never an uploaded one. That matters because joblib, like pickle, can run code while
loading.

**Versions.** major = the inputs change (breaks callers) · minor = retrained on the same inputs ·
patch = metadata only.

## Limitations and next steps

- **Synthetic only.** Nothing here transfers to real clinics.
- **Age bias is measured, not removed.** Supportive use only. *Next:* a v2 model without age, with its
  own validation and test set.
- **One model version, no monitoring.** *Next:* log estimates (without inputs) and compare predicted
  with actual rates over time, to catch drift.
- **Calibration was checked once,** on validation. *Next:* re-check on new data before any change.
- **The SHA-256 check is not attacker-proof** (see above).
- **Byte-identical rebuilds** are only promised on the building platform.
- **The real-browser check is not in CI.**
- **One appointment per request;** there is no batch endpoint.

---

# Week 2: Role-Based Health Profiles and Database Engineering

Week 2 builds on the Week 1 app (copied into this folder; everything in the Week 1 section below still works).
It has two parts:

1. **Role-Based Health Profiles and Database Engineering** (Full-Stack AI/ML track): profile completion
   status, audit events for profile edits and admin actions, new composite indexes with EXPLAIN evidence.
2. **CareConnect** (bonus, from the frontend brief): a directory for finding fictional wellness
   professionals and requesting an appointment. Frontend-only.

## Week 2 checklist: Role-Based Health Profiles and Database Engineering

| Requirement | How / where |
|---|---|
| User signup + JWT login; admins only via management command + session login | Kept from Week 1: `accounts/`, `adminpanel/`, `create_admin`. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Profile sections: demographics (fictional), emergency contact, wellness preferences | `profiles/models.py`, edited on `/profile` |
| **Profile completion status** | `profiles/completion.py` (pure rules) → stored `completion_status` column, recomputed on every save; API returns `{status, percent, missing_sections}`; progress bar on `/profile`; admin filter `?completion=` |
| User-owned profile CRUD | `POST/GET/PATCH/DELETE /api/profiles/me/` (create, read, update, delete): always resolved from the token, there is no `/profiles/<id>` for members. Delete removes the profile, keeps the account, and is audited as `profile.deleted` |
| Admin-only listing/search | `GET /api/admin/profiles/?search=&status=&completion=&ordering=&page=` |
| **Audit events** for profile edits and admin actions, no secrets or sensitive payloads | `audit/` app: append-only `AuditEvent` (actor, role, action, profile, changed field **names**, request id). Recorded on signup, profile create/update, admin login/logout, profile view, deactivate/activate. `GET /api/admin/audit-events/`; "Activity" table on the admin profile page |
| Pagination, filtering, migrations, API docs | DRF pagination; filters validated (bad values → 400); migrations `profiles/0002_completion_status` (with data backfill) and `audit/0001_initial`; Swagger at `/api/docs/`, examples in [docs/API.md](docs/API.md) |
| Hashed passwords, JWT expiry/refresh, secure token storage, CSRF for admin sessions | Argon2id; 10-min access / 7-day rotating single-use refresh in HttpOnly cookies; CSRF on every unsafe route |
| Normalized relations, FKs, unique/indexed fields, composite indexes justified by query patterns | `User 1—1 HealthProfile 1—* AuditEvent`; composite indexes `(status, created_at)`, `(completion_status, created_at)`, `(profile, created_at)`, `(action, created_at)`. Each comment in the model names the query it serves |
| No horizontal privilege escalation | Members only reach `/profiles/me/`; tests `test_profiles.py`, `test_user_auth.py` |
| Validate input, hide sensitive fields, test role boundaries | Serializer validation; `completion` and `status` read-only; audit stores no values (test `test_values_and_secrets_are_never_stored`) |
| **Acceptance:** user can't reach another profile or admin routes | `test_user_jwt_gives_no_admin_privileges`, `test_users_and_anonymous_cannot_read_the_audit_log`, browser checks |
| **Acceptance:** admin session and user JWT paths stay distinct | `test_admin_session_does_not_authenticate_user_endpoints`, `DEFAULT_AUTHENTICATION_CLASSES = []` |
| **Acceptance:** migrations, indexes and EXPLAIN evidence | [docs/explain-postgres.md](docs/explain-postgres.md): completion list 5.5 ms → 0.20 ms, audit history 7.0 ms → 0.08 ms (PostgreSQL, 20k profiles / 60k events) |

![Audit trail on the admin profile page](docs/screenshots/w2-08-admin-audit-trail.png)

**Evidence:** [Week 2 requirement checklist](docs/REQUIREMENTS-week2.md) · [review fixes](docs/review-fixes.md) · CI: `.github/workflows/ci.yml`

**Verification (run by Claude Code in development; CI re-runs it on every push):** `pytest` 192 passed + 1 PostgreSQL-only skip (SQLite), full suite also on PostgreSQL 14.21 · `npm test` 37 passed · browser runs from **before** the review fixes, not re-run since: `e2e/run_audit_e2e.py` 15/15 (incl. delete → recreate) ·
`e2e/run_e2e.py` 24/24 (Week 1 flows still work) · `e2e/run_week2_e2e.py` 33/33.

```bash
# Real-browser check of completion + audit (backend and frontend running, seed_demo done)
python e2e/run_audit_e2e.py "<admin password>" docs/screenshots
python backend/manage.py explain_queries     # query plans for every indexed lookup
```

---

## CareConnect checklist (bonus, frontend brief)

![Directory](docs/screenshots/w2-01-directory.png)


| Requirement | Where |
|---|---|
| `/professionals` and `/professionals/[id]` routes (App Router) | `frontend/app/professionals/` |
| Single typed JSON source (professionals, specialties, locations, fees, availability) | `frontend/data/professionals.json` + `frontend/lib/professionals.ts` |
| JSON validated at import time (unknown references, bad times, duplicate ids, online-only + in-person…) | `validateDirectory()` in `lib/professionals.ts` |
| Multi-criteria search + filters (text, specialties (multi), location, visit type, day, max fee) | `components/professionals/ProfessionalFilters.tsx`, `lib/filters.ts` |
| Sorting (name, fee ↑/↓, experience) | `lib/filters.ts` |
| Empty state + one-click reset | `app/professionals/page.tsx` |
| Query-parameter persistence (refresh / share / back-forward) | URL is the filter state |
| Multi-step appointment request (4 steps, validation, Previous/Next, review, no real booking) | `components/professionals/AppointmentRequestForm.tsx`, `lib/appointment.ts` |
| Draft persisted locally (survives refresh) | `localStorage` key `hp.appointmentDraft.v1.<id>` |
| Favourites with local persistence + `/saved` page | `lib/favorites.ts`, `app/saved/` |
| Accessible navigation menu (skip link, `aria-current`, mobile disclosure, Escape) | `components/ui/SiteNav.tsx`, `components/ui/Layout.tsx` |
| Reusable typed components: Card, Filter, FormField, Stepper, Badge, Layout | `frontend/components/ui/` |
| Shared design tokens / CSS variables | top of `frontend/app/globals.css` |
| Invalid professional id → not-found UI (HTTP 404) | `app/professionals/[id]/not-found.tsx` |
| Client/server boundaries + state-management choice documented | [docs/WEEK2.md](docs/WEEK2.md) |

**Acceptance checks**, verified in a real browser by `e2e/run_week2_e2e.py` (33/33 passing):
direct navigation to a profile URL ✓ · filters combine and reset, URL reflects them ✓ · form errors are
accessible (error summary with focus, `aria-invalid`, `aria-describedby`) ✓ · draft survives refresh ✓ ·
mobile layout without horizontal scroll ✓.

## Run Week 2

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000/professionals
```
(The backend is only needed for the Week 1 member/admin pages; see "Quick start" below.)

## Week 2 tests

```bash
cd frontend
npm test               # 33 unit tests (Vitest): data validation, filters, URL round-trip, form rules
npm run typecheck
npm run build          # also fails if data/professionals.json is invalid

# Real-browser acceptance run (needs: pip install playwright && playwright install chromium)
npm run build && npm start      # in one terminal
python ../e2e/run_week2_e2e.py http://127.0.0.1:3000 ../docs/screenshots
```

| | |
|---|---|
| ![Form errors](docs/screenshots/w2-04-form-errors.png) | ![Mobile](docs/screenshots/w2-06-mobile.png) |

## Week 2 limitations

- Favourites and drafts live in this browser only (`localStorage`); they are not tied to the Week 1 account
  and don't sync across devices. Intentional for this week: Week 3 adds an API.
- Availability is a weekly template, not real dated slots, and nothing prevents double requests.
- Search is a simple substring match across a 16-item list; it would move server-side with real data.
- On small screens the filter panel is long; a collapsible "Filters" drawer would be the next improvement.

---

# Week 1: role-based profile builder

Role-based HealthTech profile app with **two independent authentication systems**:

- **Members** sign up themselves and manage only their own wellness profile. Auth: short-lived **JWT in HttpOnly cookies**.
- **Admins** are provisioned by a command (no self-registration) and review profiles. Auth: **server-side sessions**.

> Educational prototype. All data is synthetic. It stores wellness preferences, **not** medical records, and gives no medical advice.

![Admin dashboard](docs/screenshots/04-admin-dashboard.png)

## Features

| Member | Admin |
|---|---|
| Sign up (name, email, password), sign in/out | Sign in/out (session), no signup path exists |
| View/edit own profile: name, DOB *or* age range, contact preference, wellness goals, allergies, emergency contact, lifestyle notes | List profiles with search, status filter, sorting, pagination |
| Silent token refresh, field-level validation errors | View full profile detail |
| Cannot see or address anyone else's data | Deactivate / reactivate a profile (blocks sign-in, kills live tokens) |

## Stack

Django 5.2 + Django REST Framework · SimpleJWT · PostgreSQL (SQLite fallback) · Next.js 15 (App Router, TypeScript) · pytest · Playwright (E2E, run manually).
Rationale and trade-offs: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

Requirements: Python 3.11+, Node 20+. PostgreSQL is optional (SQLite is used if `DATABASE_URL` is unset).

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/init_env.py        # creates .env with fresh random secrets, prints demo passwords ONCE
python manage.py migrate
python manage.py seed_demo        # demo admin + 6 synthetic members (idempotent)
python manage.py runserver        # http://127.0.0.1:8000

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev                       # http://localhost:3000  (proxies /api/* to :8000)
```

Demo accounts come from the values `init_env.py` printed (also in your local, git-ignored `backend/.env`):
admin `admin@example.test`; members such as `amina.rahman@example.test`.

**PostgreSQL:** `docker compose up -d db`, then set
`DATABASE_URL=postgres://healthprofile:healthprofile@localhost:5432/healthprofile` in `backend/.env` and re-run `migrate` + `seed_demo`.

**Create another admin** (password via env var or prompt, never a CLI argument):
```bash
ADMIN_PASSWORD='a-strong-passphrase' python manage.py create_admin --email you@example.test
```

## Tests

```bash
cd backend && pytest        # 155 tests (125 Week 1 + 30 Week 2), ~2 s; also green on PostgreSQL
cd frontend && npm run typecheck && npm run build
```

Covered: valid/invalid signup, duplicate email (case-insensitive), password hashing, expired / tampered /
`alg:none` / wrong-type JWTs, refresh rotation and replay, logout revocation, cross-user access, admin-only
endpoints, user JWT ⇒ no admin access, admin session logout, CSRF on every state-changing route, rate limiting,
DB-level constraints and index usage, validation, and the unified error format.
A 24-step real-browser run (signup → edit → admin search → deactivate → blocked login → reactivate, forged
client state, mobile layout) lives in `e2e/run_e2e.py`; screenshots are in `docs/screenshots/`. To rerun it
(`pip install playwright`, both servers up, `seed_demo` done):
```bash
# backend with a relaxed login limit, because one run uses ~8 of the 10/min allowed by default
THROTTLE_LOGIN=1000/min python manage.py runserver
python e2e/run_e2e.py "<admin password>" docs/screenshots
```

## API

Interactive docs: **http://127.0.0.1:8000/api/docs/** (Swagger UI) · schema at `/api/schema/`.
Examples with request/response bodies: [docs/API.md](docs/API.md).

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /api/auth/csrf/` | none | Sets the `csrftoken` cookie |
| `POST /api/auth/signup/` | none | Create a member |
| `POST /api/auth/user/login/` | none | Member login → JWT cookies |
| `POST /api/auth/user/refresh/` | refresh cookie | Rotate tokens |
| `POST /api/auth/user/logout/` | none | Revoke refresh token, clear cookies |
| `GET/PATCH/POST/DELETE /api/profiles/me/` | member JWT | Own profile only (full CRUD) |
| `POST /api/admin/login/` | none | Admin login → session cookie |
| `POST /api/admin/logout/` | none | Destroy session |
| `GET /api/admin/me/` | admin session | Who am I (used by the UI on every load) |
| `GET /api/admin/profiles/` | admin session | List; `?search=&status=&completion=&ordering=&page=&page_size=` |
| `GET /api/admin/audit-events/` | admin session | Audit trail; `?action=&profile=&page=&page_size=` (read-only) |
| `GET /api/admin/profiles/{id}/` | admin session | Detail |
| `POST /api/admin/profiles/{id}/deactivate/` · `/activate/` | admin session | Change status |

All unsafe requests need `X-CSRFToken` (value of the `csrftoken` cookie). Errors share one shape:
`{"error": {"code": "...", "message": "...", "details": {...}}}`.

## Project layout

```
backend/
  config/       settings (env-driven), error envelope, urls
  accounts/     User model, JWT-cookie auth, signup/login/refresh/logout, create_admin
  profiles/     HealthProfile model, completion rules, /profiles/me, seed_demo, explain_queries
  audit/        append-only AuditEvent model, record_event() service (Week 2)
  adminpanel/   admin session auth + dashboard endpoints
  tests/        pytest suite
frontend/       Next.js app (member pages, /admin pages, lib/api.ts)
  app/professionals/, app/saved/   Week 2 routes
  components/ui/                   Week 2 reusable components
  data/, lib/                      directory JSON, filters, form model, local storage
  tests/                           Vitest unit tests
e2e/            run_e2e.py (Week 1), run_week2_e2e.py (Week 2)
docs/           WEEK2.md, ARCHITECTURE.md, API.md, ai-workflow.md, explain-postgres.md, screenshots/
```

## Security notes

Secrets only via environment variables (`backend/.env.example` is the template; real `.env` is git-ignored and was never committed).
Argon2id hashing · HttpOnly/Secure/SameSite cookies · CSRF on all unsafe routes · throttled auth endpoints ·
generic login errors (no enumeration) · role stored server-side and checked on every request · DB CHECK/UNIQUE constraints.
See "Known limitations" in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for what this prototype deliberately does not do.
