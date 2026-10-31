"""Train every candidate, choose one on validation, then score the test set exactly once.

Run:  python -m ml.train      (writes ml/reports/metrics.md and ml/reports/release-<version>.md)

Two reports, because Week 4 adds models while the served release stays fixed until a new one ships:
  metrics.md          every candidate, compared on validation. The test set is NOT scored here until the
                      final evaluation step, so no later choice (cross-validation, tuning) can be
                      influenced by test numbers.
  release-<version>.md  the candidates the served release was chosen from, with its single test score.

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
from .models import CANDIDATES, RELEASE_CANDIDATES, SIMPLICITY_ORDER, Candidate, build
from .preprocess import model_input
from .split import split

REPORT = config.ML_DIR / "reports" / "metrics.md"
RELEASE_REPORT = config.ML_DIR / "reports" / f"release-{config.MODEL_VERSION}.md"
TIE_MARGIN = 0.005  # PR-AUC differences smaller than this are treated as a tie -> the simpler model wins
# Train PR-AUC minus validation PR-AUC above this raises an overfitting WARNING, written before training.
# A warning, not a verdict: models are still judged on validation alone. Forests always fit their own
# training rows closely, so their gap is large by nature; their out-of-bag score is the fairer comparison.
OVERFIT_GAP = 0.05


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
    train_no_show_rate: float
    validation: dict  # Candidate -> Scores
    train: dict  # Candidate -> Scores on the rows it was fitted on (for the overfitting check only)
    out_of_bag: dict  # Candidate -> Scores from out-of-bag predictions (random forests only)
    oracle_validation: Scores
    chosen: Candidate
    chosen_pipeline: Pipeline
    threshold: Threshold
    test: dict  # label -> Scores (floor, best baseline, chosen, best of each family, oracle); {} if not scored
    test_threshold: Threshold | None
    improvement: "Improvement | None"  # chosen vs baseline on test, with a bootstrap interval; None if not scored
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


def overfit_warning(train: Scores, validation: Scores) -> bool:
    return train.pr_auc - validation.pr_auc > OVERFIT_GAP


def out_of_bag_probability(pipeline: Pipeline):
    """Each training row scored only by the trees that did not see it; None for models without OOB."""
    model = pipeline.named_steps["model"]
    return model.oob_decision_function_[:, 1] if hasattr(model, "oob_decision_function_") else None


def select(validation: dict) -> Candidate:
    """Highest validation PR-AUC among real models; within TIE_MARGIN of the best, the simplest wins:
    first by family (`complexity`), then by settings within the family (`within_family_simplicity`).
    The second key matters because near-tied settings can swap places between machines (see below).
    This function only ever receives validation scores."""
    real = {c: s for c, s in validation.items() if c.family != "floor"}
    best = max(s.pr_auc for s in real.values())
    contenders = [c for c, s in real.items() if s.pr_auc >= best - TIE_MARGIN]
    return min(contenders, key=lambda c: (c.complexity, c.within_family_simplicity, -real[c].pr_auc))


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


def run(df: pd.DataFrame | None = None, candidates: list[Candidate] = CANDIDATES,
        score_test: bool = True) -> TrainingResult:
    df = generate() if df is None else df
    train, validation, test = split(df)
    X_train, y_train = model_input(train), train[config.LABEL]
    X_val, y_val = model_input(validation), validation[config.LABEL]

    fitted, val_scores, train_scores, oob_scores = {}, {}, {}, {}
    for candidate in candidates:
        pipeline = build(candidate).fit(X_train, y_train)
        fitted[candidate] = pipeline
        val_scores[candidate] = score(y_val, pipeline.predict_proba(X_val)[:, 1])
        train_scores[candidate] = score(y_train, pipeline.predict_proba(X_train)[:, 1])
        oob = out_of_bag_probability(pipeline)
        if oob is not None:
            oob_scores[candidate] = score(y_train, oob)

    chosen = select(val_scores)
    chosen_val_probability = fitted[chosen].predict_proba(X_val)[:, 1]
    threshold_value = choose_threshold(y_val, chosen_val_probability)

    picks = {
        "floor": best_of(val_scores, family="floor"),
        "baseline": best_of(val_scores, family="baseline"),
        "best logistic + engineered": best_of(val_scores, name="logreg_engineered"),
        **({"best random forest": best_of(val_scores, name="random_forest")}
           if any(c.name == "random_forest" for c in candidates) else {}),
        "best gradient boosting": best_of(val_scores, name="gradient_boosting"),
        "chosen": chosen,
    }
    test_scores, test_threshold, improvement = (evaluate_on_test(fitted, picks, test, threshold_value)
                                                if score_test else ({}, None, None))

    return TrainingResult(
        data_sha256=dataset_hash(df),
        split_sizes={"train": len(train), "validation": len(validation), "test": len(test)},
        train_no_show_rate=float(y_train.mean()),
        validation=val_scores,
        train=train_scores,
        out_of_bag=oob_scores,
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


def _fit_row(c: Candidate, result: "TrainingResult") -> str:
    tr, va = result.train[c], result.validation[c]
    oob = result.out_of_bag.get(c)
    oob_cell = f"{oob.pr_auc:.3f} ({oob.pr_auc - va.pr_auc:+.3f})" if oob else "–"
    flag = "⚠ warning" if overfit_warning(tr, va) else ""
    return (f"| {c.label} | {tr.pr_auc:.3f} | {va.pr_auc:.3f} | {tr.pr_auc - va.pr_auc:+.3f} | {oob_cell} "
            f"| {tr.roc_auc:.3f} | {va.roc_auc:.3f} | {tr.brier:.4f} | {va.brier:.4f} | {flag} |")


NOT_SCORED = """## 4. Test set: not scored yet

The test set is scored once, in the final evaluation step, after cross-validation and tuning are done.
Until then no test number exists in this report, so none can influence a choice.

## 5. Did the improved model really beat the baseline?

Answered on the test set in the final evaluation step."""


def _test_sections(result: TrainingResult) -> tuple[str, str]:
    floor_test = next(s for k, s in result.test.items() if k.startswith("floor"))
    oracle_test = result.test["oracle ceiling (true probability)"]
    test_rows = "\n".join(_row(k, s, floor_test, oracle_test, "**" if k.startswith("chosen") else "")
                          for k, s in result.test.items())
    baseline_test = next(s for k, s in result.test.items() if k.startswith("baseline"))
    chosen_test = next(s for k, s in result.test.items() if k.startswith("chosen"))
    tt, imp = result.test_threshold, result.improvement
    threshold_row = (f"| test (same threshold, applied once) | {tt.value:.4f} | {tt.precision:.3f} | {tt.recall:.3f} "
                     f"| {tt.f1:.3f} | {100 * tt.flagged_share:.1f}% |\n\n"
                     f"In words: of the appointments the model flags, about {100 * tt.precision:.0f}% are real no-shows\n"
                     f"(precision), and it catches about {100 * tt.recall:.0f}% of all no-shows (recall).")
    sections = f"""## 4. Test set: scored once, after every decision above

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
until it passes."""
    return threshold_row, sections


COMPARISON_TITLE = "Model comparison: synthetic appointment no-shows"
RELEASE_TITLE = (f"Served release {config.MODEL_NAME}-{config.MODEL_VERSION}: how it was chosen and its test score\n\n"
                 "> Rebuilt from the candidates this release was chosen from (Week 3), so the served model stays\n"
                 "> exactly reproducible. The Week 4 comparison of every model is in [metrics.md](metrics.md).")


def build_report(result: TrainingResult, title: str = COMPARISON_TITLE) -> str:
    floor_val = next(s for c, s in result.validation.items() if c.family == "floor")
    oracle_val = result.oracle_validation
    val_rows = "\n".join(
        _row(c.label, s, floor_val, oracle_val, "**" if c == result.chosen else "")
        for c, s in sorted(result.validation.items(), key=lambda kv: (kv[0].complexity, kv[0].label))
    )
    t = result.threshold
    best_real = max((s.pr_auc for c, s in result.validation.items() if c.family != "floor"))
    chosen_val = result.validation[result.chosen]
    imp = result.improvement
    fit_rows = "\n".join(_fit_row(c, result) for c in sorted(result.validation, key=lambda c: (c.complexity, c.label))
                         if c.family != "floor")
    warned = [c for c in result.validation if c.family != "floor" and overfit_warning(result.train[c], result.validation[c])]
    warned_forests = [c for c in warned if c in result.out_of_bag]
    simplicity = " < ".join(f"`{n}`" for n in SIMPLICITY_ORDER)
    engineered_sentence = (
        "The engineered features (log lead time, no-show rate, has-history, reminder × lead time) helped the "
        "logistic regression capture the curve, habit and interaction found in the EDA."
        if imp is None or imp.low > 0 else
        "The engineered features did not produce a clear gain over the raw baseline on test; see section 5."
    )
    threshold_test_row, test_sections = _test_sections(result) if imp else (
        "| test | not scored yet | | | | |",
        NOT_SCORED,
    )

    return f"""# {title}

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

### Train versus validation (overfitting check)

The same metrics on the training rows each model was fitted on. A large drop from train to validation
means the model learned details of its own training rows that don't carry over.

Rule, fixed before training: a train − validation PR-AUC gap above {OVERFIT_GAP} raises a **warning**.
It is a warning, not a verdict; every model is still judged on its validation score alone. Random
forests always fit their own training rows closely, because each tree memorises the rows it was grown
on, so their plain training score overstates them by nature. The **out-of-bag** column is fairer: each
training row is scored only by the trees that never saw it (number in brackets: out-of-bag − validation).

| model | train PR-AUC | validation PR-AUC | gap | out-of-bag PR-AUC | train ROC-AUC | validation ROC-AUC | train Brier | validation Brier | |
|---|---|---|---|---|---|---|---|---|---|
{fit_rows}

{len(warned)} of {len([c for c in result.validation if c.family != "floor"])} models raised the warning{
"" if not warned else f" ({len(warned_forests)} of them random forests)"}. {
"For the forests, the out-of-bag score stays close to the validation score, so their training score overstates them, as expected; validation decides." if warned_forests and all(abs(result.out_of_bag[c].pr_auc - result.validation[c].pr_auc) < OVERFIT_GAP for c in warned_forests)
else "See the table for which models and by how much; validation decides." if warned else
"No model's training score runs far ahead of its validation score."}

## 2. Choice

**Chosen: {result.chosen.label}** (validation PR-AUC {chosen_val.pr_auc:.3f}).

Rule, fixed before training: highest validation PR-AUC; any model within {TIE_MARGIN} of the best
(here {best_real:.3f}) counts as tied, and among tied models the simplest wins. Simplicity order,
also fixed before training: {simplicity}. Logistic regression comes first because its weights can be
read and explained; a forest's trees are independent and averaged, while boosting builds trees in
sequence with interacting settings. Within the random forests: shallower trees first, then larger
leaves (both limit memorising); the number of trees doesn't cause overfitting, only a steadier vote, so
on a remaining tie more trees win. Rows above are in this order, not by score, so near-ties can't
reorder them between machines.

Not used, on purpose: `class_weight="balanced"`. It would push every probability up, hurt the Brier
score and break the meaning of "16% means 16%". The imbalance is handled by the metric (PR-AUC) and
by choosing the decision threshold below.

## 3. Decision threshold (chosen on validation)

The model outputs a probability; to act on it ("send an extra reminder") we need a cut-off. It is
chosen to maximise F1 on validation. With 16% positives it is far below 0.5.

| | threshold | precision | recall | F1 | appointments flagged |
|---|---|---|---|---|---|
| validation (where it was chosen) | {t.value:.4f} | {t.precision:.3f} | {t.recall:.3f} | {t.f1:.3f} | {100 * t.flagged_share:.1f}% |
{threshold_test_row}

{test_sections}

## 6. What this shows

- Every real model beats the floor, so there is genuine signal in the features.
- {engineered_sentence}
- The gap to the oracle ceiling is what is left: mostly the hidden per-patient reliability, which no
  feature can fully reveal, plus the coin-flip noise built into every outcome.
- Gradient boosting with depth 6 scored below depth 3: the extra depth fits noise in the training rows.
- Errors per group, calibration, age bias and whether the planted formula was learned:
  [errors.md](errors.md).
"""


def comparison_report(df: pd.DataFrame | None = None) -> str:
    return build_report(run(df, score_test=False))


def release_report(df: pd.DataFrame | None = None) -> str:
    return build_report(run(df, candidates=RELEASE_CANDIDATES), RELEASE_TITLE)


def main():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for path, build_text in [(REPORT, comparison_report), (RELEASE_REPORT, release_report)]:
        path.write_text(build_text())
        print(f"written to: {path}")


if __name__ == "__main__":
    main()
