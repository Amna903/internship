# Week 3 design notes

The "why" behind each step of the ML pipeline, in the order it was built. The generated reports hold
the numbers. This file explains the choices and what was checked. Every step has its own tests.

## Step 0: scope

- **Task:** synthetic appointment no-show likelihood, the example the brief itself names.
- **Not diagnostic:** it predicts attendance, not health. The only action it supports is an extra
  reminder.
- **Requirement checklist first:** [REQUIREMENTS.md](REQUIREMENTS.md) lists every brief line before any
  code, after Week 2's lesson of starting from the wrong brief.

## Step 1: data (`ml/data.py`, [DATA_CARD](DATA_CARD.md))

- **Generator:** a seeded NumPy generator, rather than downloaded or LLM-made data. There's no privacy
  or licence question, it's reproducible, and we know the **true probability** of every row.
- **Formula structure:** a curve (lead time), an interaction (a reminder matters more when booked far
  ahead) and a hidden per-patient habit. Without these, a plain logistic regression would already
  match the formula, and "baseline vs improved" would mean nothing.
- **Problems planted on purpose:** missing distances, class imbalance and an age bias. The brief asks
  us to handle and document each of these.
- **Column roles:** every column has exactly one role in `ml/config.py`. IDs, the label and the true
  probability can never be features.

## Step 2: exploratory analysis ([eda.md](../backend/ml/reports/eda.md))

- **Each finding ends with a decision:** curve → `log1p(lead time)`; interaction → `reminder × lead
  time`; habit → past no-show ratio; repeat patients → split by patient.
- **Missing distance:** the no-show rate gap had p = 0.03. We *know* the blanks are random, so this was
  a false alarm, a reminder that one significant test is not proof. The model gets a missing flag
  either way.
- **Leakage check:** a single-feature check flags any column that predicts too well on its own. A test
  plants a `checked_in` column to prove the check works.

## Step 3: split and preprocessing (`ml/split.py`, `ml/features.py`, `ml/preprocess.py`)

- **Split:** 60/20/20 with `GroupShuffleSplit` on `patient_id`, so no patient appears in two parts.
- **Edge cases:**
  - `log1p`, not `log`, because a same-day appointment has lead time 0 and `log(0)` is −∞;
  - the past no-show ratio is 0 when there is no history, plus a `has_history` flag, so "new patient"
    and "never missed" stay distinguishable and nothing is divided by zero.
- **Training rows only:** everything that learns a value (median, scaling, categories) does so on
  training rows, inside one Pipeline.
- **`ColumnGuard`:** rejects any forbidden or missing column.

## Step 4: models ([metrics.md](../backend/ml/reports/metrics.md))

- **Candidates:** a floor, a baseline and two improved model families, on a small fixed grid.
- **Selection rule, written before training:** the highest validation PR-AUC wins. Within 0.005, the
  simpler model wins.
- **Test set:** used once, after the model and the cut-off were final. Flipping every test label leaves
  the choice unchanged, and a test checks exactly that.
- **"Improved beats baseline" is reported, not forced:** a bootstrap interval decides the verdict, and
  the code is never adjusted until a test passes.
- **No class weighting:** it would break honest probabilities.

## Step 5: error analysis ([errors.md](../backend/ml/reports/errors.md))

- **Calibration rule accounts for sampling noise:** a Bonferroni limit across 10 bins. A naive
  2-standard-error rule would have raised two false alarms on this data.
- **No changes after the test set:** recalibration, if it had been needed, and dropping age are
  reported as findings and next steps, not applied.
- **Synthetic-only check:** the true probability shows about two-thirds of errors are unavoidable coin
  flips.
- **Learned directions:** checked by changing one input at a time. Raw coefficients are unreliable
  here, because lead time appears in three features.

## Step 6: release (`ml/artifact.py`, `ml/inference.py`)

- **One file:** the whole Pipeline, plus timestamp-free metadata. Rebuilding in a fresh process
  reproduces it.
- **Loading checks, in order:** files exist → version and schema → exact scikit-learn version →
  SHA-256 → only then unpickle.
- **What the SHA-256 does and doesn't do:** it catches accidents, not attackers. We only ever load our
  own committed file.
- **Output wording:** "Extra reminder suggested" / "Standard reminder", never "high risk".

## Step 7: API (`predictions/`, [API.md](API.md))

- **Week 2 rules:** admin session, CSRF, a rate limit, and an audit event that stores the model
  version, never the inputs.
- **Strict validation:** a schema shared with the model metadata. `true`, `"14"` and `14.5` are not
  integers; unknown fields are rejected; all errors are reported in one response.
- **Model failure:** returns `503`; the reason goes to the server log only.
- **Audit column:** the new nullable `detail` column is added with `ALTER TABLE ADD COLUMN`, so the
  append-only triggers survive. A test checks this.

## Step 8: dashboard (`frontend/app/admin/predictions/`)

- **Shared schema:** one JSON file that both sides test against.
- **"Fill example" buttons:** each example's promised result is checked against the real model.
- **Stale results:** any edit clears the old result.
- **Server is the authority:** server 400s are shown next to their fields.
- **Real-browser check:** 17/17 locally, with screenshots.
