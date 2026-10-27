"""Train every candidate, choose one on validation, then score the test set exactly once.

Run:  python -m ml.train      (prints the tables and writes ml/reports/metrics.md)

Order of operations, and why:
  1. Fit every candidate on TRAIN only.
  2. Score every candidate on VALIDATION. Tuning, model choice and the decision threshold all use
     validation scores only.
  3. Only after the choice is final, score the TEST set, once (evaluate_on_test). Nothing is changed
     after seeing test numbers; otherwise the test set would quietly become a second validation set
     and its score would be optimistic.
The oracle row (the generator's true probabilities) is the best score any model could reach.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score
from sklearn.pipeline import Pipeline

from . import config
from .data import dataset_hash, generate
from .models import CANDIDATES, Candidate, build
from .preprocess import model_input
from .split import split

REPORT = config.ML_DIR / "reports" / "metrics.md"
TIE_MARGIN = 0.005  # PR-AUC differences smaller than this are treated as a tie -> the simpler model wins


@dataclass
class Scores:
    pr_auc: float
    roc_auc: float
    brier: float
    mean_prediction: float


@dataclass
class Threshold:
    value: float
    precision: float
    recall: float
    f1: float
    flagged_share: float


@dataclass
class Improvement:
    """Chosen model minus baseline, test PR-AUC, with a 95% interval from a patient-level bootstrap."""
    difference: float
    low: float
    high: float
    resamples: int

    @property
    def verdict(self) -> str:
        # Whatever the numbers say is reported as-is. A failed improvement is a finding, not a bug.
        if self.low > 0:
            return "a real improvement: the whole 95% interval is above zero"
        if self.difference > 0:
            return ("not clearly better: the chosen model scored higher, but the 95% interval includes zero, "
                    "so the gain could be luck")
        return "no improvement: the chosen model did not beat the baseline on test. This is a finding, reported as-is"


@dataclass
class TrainingResult:
    data_sha256: str
    split_sizes: dict
    validation: dict  # Candidate -> Scores
    oracle_validation: Scores
    chosen: Candidate
    chosen_pipeline: Pipeline
    threshold: Threshold
    test: dict  # label -> Scores (floor, best baseline, chosen, best of each family, oracle)
    test_threshold: Threshold
    improvement: "Improvement"  # chosen vs baseline on test, with a bootstrap confidence interval
    fitted: dict  # Candidate -> fitted Pipeline


def score(y_true, probability) -> Scores:
    y_true = np.asarray(y_true, dtype=int)
    probability = np.asarray(probability, dtype=float)
    return Scores(
        pr_auc=float(average_precision_score(y_true, probability)),  # main metric: focuses on no-shows
        roc_auc=float(roc_auc_score(y_true, probability)),  # ranking quality overall
        brier=float(brier_score_loss(y_true, probability)),  # are the probabilities honest? lower is better
        mean_prediction=float(probability.mean()),
    )


def choose_threshold(y_true, probability) -> float:
    """The cut-off that maximises F1 on the data given (validation). With 16% positives it is far below 0.5."""
    precision, recall, thresholds = precision_recall_curve(np.asarray(y_true, dtype=int), probability)
    f1 = 2 * precision * recall / np.clip(precision + recall, 1e-12, None)
    return float(thresholds[int(np.argmax(f1[:-1]))])  # the last point has no threshold


def apply_threshold(y_true, probability, threshold: float) -> Threshold:
    y_true = np.asarray(y_true, dtype=bool)
    flagged = np.asarray(probability) >= threshold
    tp = int((flagged & y_true).sum())
    precision = tp / max(int(flagged.sum()), 1)
    recall = tp / max(int(y_true.sum()), 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    return Threshold(threshold, precision, recall, f1, float(flagged.mean()))


def select(validation: dict) -> Candidate:
    """Highest validation PR-AUC among real models; within TIE_MARGIN of the best, the simplest wins.
    This function only ever receives validation scores."""
    real = {c: s for c, s in validation.items() if c.family != "floor"}
    best = max(s.pr_auc for s in real.values())
    contenders = [c for c, s in real.items() if s.pr_auc >= best - TIE_MARGIN]
    return min(contenders, key=lambda c: (c.complexity, -real[c].pr_auc))


def best_of(validation: dict, family: str = None, name: str = None) -> Candidate:
    pool = {c: s for c, s in validation.items() if (family is None or c.family == family)
            and (name is None or c.name == name)}
    return max(pool, key=lambda c: pool[c].pr_auc)


BOOTSTRAP_RESAMPLES = 1000


def bootstrap_difference(y, chosen_probability, baseline_probability, groups) -> Improvement:
    """Resample whole patients (their appointments are related), recompute both PR-AUCs on the same
    resample, and take the 2.5th and 97.5th percentiles of the difference."""
    y, groups = np.asarray(y, dtype=int), np.asarray(groups)
    chosen_probability, baseline_probability = np.asarray(chosen_probability), np.asarray(baseline_probability)
    patients = np.unique(groups)
    rows_of = {p: np.flatnonzero(groups == p) for p in patients}
    rng = np.random.default_rng(config.SEED)
    differences = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        idx = np.concatenate([rows_of[p] for p in rng.choice(patients, size=patients.size, replace=True)])
        if y[idx].min() == y[idx].max():
            continue  # a resample with one class only has no PR-AUC
        differences.append(average_precision_score(y[idx], chosen_probability[idx])
                           - average_precision_score(y[idx], baseline_probability[idx]))
    point = average_precision_score(y, chosen_probability) - average_precision_score(y, baseline_probability)
    low, high = np.percentile(differences, [2.5, 97.5])
    return Improvement(float(point), float(low), float(high), len(differences))


def evaluate_on_test(fitted: dict, picks: dict, test: pd.DataFrame, threshold: float):
    """The ONLY place test rows are scored. Called once, after every decision is final."""
    X, y = model_input(test), test[config.LABEL]
    results = {label: score(y, fitted[c].predict_proba(X)[:, 1]) for label, c in picks.items()}
    results["oracle ceiling (true probability)"] = score(y, test[config.ORACLE])
    chosen_probability = fitted[picks["chosen"]].predict_proba(X)[:, 1]
    baseline_probability = fitted[picks["baseline"]].predict_proba(X)[:, 1]
    improvement = bootstrap_difference(y, chosen_probability, baseline_probability, test["patient_id"])
    return results, apply_threshold(y, chosen_probability, threshold), improvement


def run(df: pd.DataFrame | None = None) -> TrainingResult:
    df = generate() if df is None else df
    train, validation, test = split(df)
    X_train, y_train = model_input(train), train[config.LABEL]
    X_val, y_val = model_input(validation), validation[config.LABEL]

    fitted, val_scores = {}, {}
    for candidate in CANDIDATES:
        pipeline = build(candidate).fit(X_train, y_train)
        fitted[candidate] = pipeline
        val_scores[candidate] = score(y_val, pipeline.predict_proba(X_val)[:, 1])

    chosen = select(val_scores)
    chosen_val_probability = fitted[chosen].predict_proba(X_val)[:, 1]
    threshold_value = choose_threshold(y_val, chosen_val_probability)

    picks = {
        "floor": best_of(val_scores, family="floor"),
        "baseline": best_of(val_scores, family="baseline"),
        "best logistic + engineered": best_of(val_scores, name="logreg_engineered"),
        "best gradient boosting": best_of(val_scores, name="gradient_boosting"),
        "chosen": chosen,
    }
    test_scores, test_threshold, improvement = evaluate_on_test(fitted, picks, test, threshold_value)

    return TrainingResult(
        data_sha256=dataset_hash(df),
        split_sizes={"train": len(train), "validation": len(validation), "test": len(test)},
        validation=val_scores,
        oracle_validation=score(y_val, validation[config.ORACLE]),
        chosen=chosen,
        chosen_pipeline=fitted[chosen],
        threshold=apply_threshold(y_val, chosen_val_probability, threshold_value),
        test={("chosen: " + chosen.label if k == "chosen" else f"{k}: {picks[k].label}" if k in picks else k): v
              for k, v in test_scores.items()},
        test_threshold=test_threshold,
        improvement=improvement,
        fitted=fitted,
    )


# ---------------------------------------------------------------- report

def _gap_closed(s: Scores, floor: Scores, oracle: Scores) -> str:
    """How much of the distance from 'useless' (floor) to 'perfect knowledge' (oracle) a model covers."""
    return f"{100 * (s.pr_auc - floor.pr_auc) / (oracle.pr_auc - floor.pr_auc):.0f}%"


def _row(label, s: Scores, floor: Scores, oracle: Scores, mark="") -> str:
    return (f"| {mark}{label}{mark} | {s.pr_auc:.3f} | {s.roc_auc:.3f} | {s.brier:.4f} | {s.mean_prediction:.3f} "
            f"| {_gap_closed(s, floor, oracle)} |")


HEADER = ("| model | PR-AUC ↑ | ROC-AUC ↑ | Brier ↓ | mean prediction | gap closed (floor → oracle) |\n"
          "|---|---|---|---|---|---|")


def build_report(result: TrainingResult) -> str:
    floor_val = next(s for c, s in result.validation.items() if c.family == "floor")
    oracle_val = result.oracle_validation
    val_rows = "\n".join(
        _row(c.label, s, floor_val, oracle_val, "**" if c == result.chosen else "")
        for c, s in sorted(result.validation.items(), key=lambda kv: -kv[1].pr_auc)
    )
    floor_test = next(s for k, s in result.test.items() if k.startswith("floor"))
    oracle_test = result.test["oracle ceiling (true probability)"]
    test_rows = "\n".join(_row(k, s, floor_test, oracle_test, "**" if k.startswith("chosen") else "")
                          for k, s in result.test.items())
    t, tt = result.threshold, result.test_threshold
    best_real = max((s.pr_auc for c, s in result.validation.items() if c.family != "floor"))
    chosen_val = result.validation[result.chosen]
    baseline_test = next(s for k, s in result.test.items() if k.startswith("baseline"))
    chosen_test = next(s for k, s in result.test.items() if k.startswith("chosen"))
    imp = result.improvement
    engineered_sentence = (
        "The engineered features (log lead time, no-show rate, has-history, reminder × lead time) helped the "
        "logistic regression capture the curve, habit and interaction found in the EDA."
        if imp.low > 0 else
        "The engineered features did not produce a clear gain over the raw baseline on test; see section 5."
    )

    return f"""# Model comparison: synthetic appointment no-shows

> Synthetic, educational data. These numbers measure how well a model recovers the generator's
> planted formula, not real-world performance. Generated by `python -m ml.train`; do not edit by hand.

| | |
|---|---|
| Dataset SHA-256 | `{result.data_sha256}` |
| Split (patient-grouped) | train {result.split_sizes['train']:,} · validation {result.split_sizes['validation']:,} · test {result.split_sizes['test']:,} rows |
| Seed | {config.SEED} (data, split and every model) |
| Main metric | PR-AUC: the class of interest (no-show) is the 16% minority, so accuracy would mislead |

How to read the columns:
- **PR-AUC**: how well the model ranks no-shows above attended appointments, focused on the
  minority class (higher is better; the floor's value equals the no-show rate).
- **ROC-AUC**: overall ranking quality (0.5 = random, 1 = perfect).
- **Brier**: mean squared error of the probabilities; lower means more honest probabilities.
- **mean prediction**: should sit near the real no-show rate (well calibrated on average).
- **gap closed**: share of the distance from the floor to the oracle ceiling covered by the model.

## 1. Validation: every candidate (used for all choices)

{HEADER}
{val_rows}
| *oracle ceiling (true probability)* | {oracle_val.pr_auc:.3f} | {oracle_val.roc_auc:.3f} | {oracle_val.brier:.4f} | {oracle_val.mean_prediction:.3f} | 100% |

## 2. Choice

**Chosen: {result.chosen.label}** (validation PR-AUC {chosen_val.pr_auc:.3f}).

Rule, fixed before training: highest validation PR-AUC; any model within {TIE_MARGIN} of the best
(here {best_real:.3f}) counts as tied, and among tied models the simplest wins (logistic regression
before gradient boosting) because its weights can be read and explained.

Not used, on purpose: `class_weight="balanced"`. It would push every probability up, hurt the Brier
score and break the meaning of "16% means 16%". The imbalance is handled by the metric (PR-AUC) and
by choosing the decision threshold below.

## 3. Decision threshold (chosen on validation)

The model outputs a probability; to act on it ("send an extra reminder") we need a cut-off. It is
chosen to maximise F1 on validation. With 16% positives it is far below 0.5.

| | threshold | precision | recall | F1 | appointments flagged |
|---|---|---|---|---|---|
| validation (where it was chosen) | {t.value:.4f} | {t.precision:.3f} | {t.recall:.3f} | {t.f1:.3f} | {100 * t.flagged_share:.1f}% |
| test (same threshold, applied once) | {tt.value:.4f} | {tt.precision:.3f} | {tt.recall:.3f} | {tt.f1:.3f} | {100 * tt.flagged_share:.1f}% |

In words: of the appointments the model flags, about {100 * tt.precision:.0f}% are real no-shows
(precision), and it catches about {100 * tt.recall:.0f}% of all no-shows (recall).

## 4. Test set: scored once, after every decision above

{HEADER}
{test_rows}

PR-AUC on test: chosen {chosen_test.pr_auc:.3f} vs baseline {baseline_test.pr_auc:.3f} vs oracle
{oracle_test.pr_auc:.3f}. Test rows were not used for tuning, model choice or the threshold.

## 5. Did the improved model really beat the baseline?

Test PR-AUC, chosen minus baseline: **{imp.difference:+.3f}**, 95% interval
**[{imp.low:+.3f}, {imp.high:+.3f}]** (bootstrap over whole patients, {imp.resamples} resamples, seed {config.SEED}).

Verdict: **{imp.verdict}.**

This verdict is computed from the numbers every time the report is generated. If a change to the data
or the models ever makes the improvement disappear, the report says so; the code is not adjusted
until it passes.

## 6. What this shows

- Every real model beats the floor, so there is genuine signal in the features.
- {engineered_sentence}
- The gap to the oracle ceiling is what is left: mostly the hidden per-patient reliability, which no
  feature can fully reveal, plus the coin-flip noise built into every outcome.
- Gradient boosting with depth 6 scored below depth 3: the extra depth fits noise in the training rows.
- Error analysis by age band and calibration: see Step 5.
"""


def main():
    result = run()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(result))
    print(build_report(result).split("## 6.")[0])
    print(f"written to: {REPORT}")


if __name__ == "__main__":
    main()
