# Supervised task: definitions

The one place that defines the Week 4 supervised task: what the model sees, what it predicts, how the data is split, and how leakage is ruled out. Brief rows **S1** and **S2**.

`tests/test_supervised_doc.py` checks every table here against the code and the generated data, so this page can't silently drift from what the pipeline does.

> Synthetic, educational data only. The model estimates whether a fictional appointment may be missed, to plan reminders. It is not a medical assessment.

## Dataset (S1)

The same seeded synthetic appointment data as Week 3, extended rather than replaced, as the brief asks ("expand the Week 3 ML system"). How it's generated, its licence and its planted problems are in [DATA_CARD.md](DATA_CARD.md).

| | |
|---|---|
| Rows | 20,076 appointments |
| Patients | 5,000 |
| Generator | `backend/ml/data.py`, `SEED = 42` |

## Label

| | |
|---|---|
| Column | `no_show` |
| 1 means | the fictional patient did not attend this appointment |
| 0 means | they attended |
| Rate | 16.4% (the minority class, so accuracy is not used to compare models) |

## Features

Each input column the model receives. The roles are defined once in `backend/ml/config.py`.

| Feature | Kind | Meaning |
|---|---|---|
| `lead_time_days` | numeric | days between booking and the appointment |
| `appointment_hour` | numeric | hour of the appointment, 7–19 |
| `prior_appointments` | numeric | this patient's appointments before this one |
| `prior_no_shows` | numeric | how many of those were missed |
| `distance_km` | numeric | distance from the clinic; sometimes blank |
| `appointment_weekday` | categorical | monday–saturday |
| `age_band` | categorical | six bands; a sensitive attribute (see the bias section of the data card) |
| `visit_type` | categorical | in_person or telehealth |
| `booking_channel` | categorical | web, phone or app |
| `reminder_sent` | boolean | whether a reminder was sent |

Engineered features, computed inside the pipeline (`backend/ml/features.py`) from the columns above:

| Feature | Formula | Why |
|---|---|---|
| `log_lead_time` | `log1p(lead_time_days)` | the effect of lead time is a curve; `log1p` because lead time can be 0 |
| `prior_no_show_rate` | `prior_no_shows / prior_appointments`, or 0 with no history | the patient's habit, without dividing by zero |
| `has_history` | 1 if `prior_appointments > 0` | keeps "new patient" apart from "never missed" |
| `reminder_x_lead` | `reminder_sent × min(lead_time_days, 30) / 30` | a reminder matters more when booked far ahead |

## Never features

Columns that exist in the data but must never reach a model. `ColumnGuard` in `backend/ml/preprocess.py` rejects any of them.

| Column | Why it exists | Why it's excluded |
|---|---|---|
| `appointment_id` | row identifier | carries no meaning; a model could memorise it |
| `patient_id` | groups the split | a model could recognise the person instead of learning patterns |
| `true_no_show_probability` | the generator's true probability, for the oracle ceiling | it is the answer itself |
| `no_show` | the label | it is what we predict |

## Split strategy

60 / 20 / 20, **grouped by patient** (`GroupShuffleSplit` on `patient_id`, seeded), so every patient's appointments land in exactly one part. If a patient appeared in both training and test, the model could score well by recognising that person instead of learning what transfers to new patients.

| Part | Rows | Patients | No-show rate | Used for |
|---|---|---|---|---|
| train | 12,126 | 3,000 | 16.45% | fitting the preprocessing and every model; cross-validation and tuning run inside this part only |
| validation | 3,998 | 1,000 | 16.16% | choosing the model and the decision threshold |
| test | 3,952 | 1,000 | 16.45% | one final score, after every choice is made |

The no-show rates of the three parts are within 0.3 percentage points of each other without stratifying, because 5,000 patients is enough for random grouping to balance them. Cross-validation in Step 3 adds stratification explicitly (`StratifiedGroupKFold`).

## Leakage checks

| Check | How | Result |
|---|---|---|
| No forbidden column reaches a model | `ColumnGuard` raises on any never-feature or missing feature | enforced on every fit and every prediction |
| No patient in two parts | intersection of patient IDs between parts | empty |
| No single feature predicts "too well" | ROC-AUC of each feature alone; above 0.80 would suggest it encodes the answer | highest is `lead_time_days` at 0.618 |
| The check above actually works | a planted `checked_in` column (the answer in disguise) | flagged |
| History counts use only the past | for each patient, `prior_no_shows` rises by exactly the previous appointment's outcome, and `prior_appointments` by exactly 1 | holds for every consecutive pair |
| Preprocessing learns from training rows only | medians, scaling and categories are fitted inside one Pipeline on `train` | by construction |
| Test set used once | scored only in `evaluate_on_test`, after the model and threshold are fixed | flipping every test label leaves the choice unchanged |

Single-feature ROC-AUC on the full dataset (0.5 = useless):

| Feature | ROC-AUC alone |
|---|---|
| `lead_time_days` | 0.618 |
| `age_band` | 0.575 |
| `prior_no_shows` | 0.566 |
| `reminder_sent` | 0.527 |
| `visit_type` | 0.526 |
| `distance_km` | 0.523 |
| `appointment_weekday` | 0.522 |
| `booking_channel` | 0.514 |
| `appointment_hour` | 0.506 |
| `prior_appointments` | 0.506 |

## Known limitation

The split is by patient, not by time. A patient's earlier and later appointments stay together, which is right for "does this transfer to new patients?", but it doesn't test "does this still work next month?". On synthetic data with no drift built in, the two answers would match; on real data a time-based split would also be needed.
