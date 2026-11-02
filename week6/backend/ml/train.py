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

import json
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, precision_recall_curve, roc_auc_score
from sklearn.pipeline import Pipeline

from . import config
from .data import dataset_hash, generate
from .models import CANDIDATES, RELEASE_CANDIDATES, SIMPLICITY_ORDER, TUNING_RESULT, Candidate, build
from .preprocess import model_input
from .split import split

REPORT = config.ML_DIR / "reports" / "metrics.md"
# The first release, chosen in Week 3 by validation. Kept exactly reproducible next to the current one.
FIRST_RELEASE = "1.0.0"
SERVED_ESTIMATOR = "logreg_engineered (C=0.1)"  # what the first (and still served) release contains
RELEASE_REPORT = config.ML_DIR / "reports" / f"release-{FIRST_RELEASE}.md"
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
    # Week 4: each algorithm at its OWN validation cut-off, scored on test: label -> (cut-off, Threshold, confusion)
    per_model_test: dict | None
    improvement: "Improvement | None"  # chosen vs baseline on test, with a bootstrap interval; None if not scored
    fitted: dict  # Candidate -> fitted Pipeline
    cv: dict | None = None  # Candidate -> fold PR-AUCs; when given, the choice is made by cross-validation
    cv_bar: float | None = None  # one-standard-error bar used for the CV choice
    rival: str | None = None  # Week 4: the model the chosen one is compared with on test (best other by CV)


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


# ---- Week 4 Step 3: choose by cross-validation ----
# Changed after Step 3's results (recorded in docs/REQUIREMENTS.md): one validation draw of ~4,000 rows
# was too noisy to separate close models; five patient-grouped folds of the 12,126 training rows are
# better evidence. Validation is kept as a confirmation check and for the decision threshold.
CONFIRMATION_SDS = 2  # the chosen model's validation PR-AUC should lie within CV mean +/- 2 fold SDs


def load_cv_scores(candidates: list[Candidate] = CANDIDATES) -> dict:
    """Candidate -> fold PR-AUCs, from the committed `python -m ml.tune` result (train folds only)."""
    result = json.loads(TUNING_RESULT.read_text())
    by_label = {g["label"]: g["fold_scores"] for g in result["grid_cv"]}
    tuned = next(r["fold_scores"] for r in result["search"] if r["params"] == result["chosen"])
    out = {}
    for c in candidates:
        if c.label in by_label:
            out[c] = by_label[c.label]
        elif dict(c.params) == result["chosen"]:
            out[c] = tuned
    return out


def select_by_cv(cv: dict) -> tuple[Candidate, float]:
    """One-standard-error rule across every family: the bar is the best mean CV PR-AUC minus one standard
    error of that mean; among real models at or above it, the simplest wins (family, then settings)."""
    real = {c: s for c, s in cv.items() if c.family != "floor"}
    means = {c: float(np.mean(s)) for c, s in real.items()}
    best = max(means, key=means.get)
    bar = means[best] - float(np.std(real[best], ddof=1)) / math.sqrt(len(real[best]))
    eligible = [c for c in real if means[c] >= bar]
    return min(eligible, key=lambda c: (c.complexity, c.within_family_simplicity, -means[c])), bar


def confirmed_by_validation(fold_scores, validation_pr_auc: float) -> bool:
    mean, sd = float(np.mean(fold_scores)), float(np.std(fold_scores, ddof=1))
    return bool(abs(validation_pr_auc - mean) <= CONFIRMATION_SDS * sd)


def best_of(validation: dict, family: str = None, name: str = None, cv: dict | None = None) -> Candidate:
    """Best of a family: by mean CV PR-AUC when CV scores are given (Week 4; near-tied validation scores swap
    between machines), otherwise by validation PR-AUC (Week 3)."""
    pool = [c for c in validation if (family is None or c.family == family) and (name is None or c.name == name)]
    if cv is not None:
        return max(pool, key=lambda c: float(np.mean(cv[c])))
    return max(pool, key=lambda c: validation[c].pr_auc)


def confusion_counts(y_true, probability, threshold: float) -> dict:
    y_true = np.asarray(y_true, dtype=bool)
    flagged = np.asarray(probability) >= threshold
    return {"tp": int((flagged & y_true).sum()), "fp": int((flagged & ~y_true).sum()),
            "fn": int((~flagged & y_true).sum()), "tn": int((~flagged & ~y_true).sum())}


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


def evaluate_on_test(fitted: dict, picks: dict, test: pd.DataFrame, threshold: float, cutoffs: dict | None = None,
                     rival: str = "baseline"):
    """The ONLY place test rows are scored. Called once, after every decision is final.
    `cutoffs` (label -> validation cut-off) adds each algorithm's confusion matrix at its own cut-off."""
    X, y = model_input(test), test[config.LABEL]
    results = {label: score(y, fitted[c].predict_proba(X)[:, 1]) for label, c in picks.items()}
    per_model = None
    if cutoffs is not None:
        per_model = {}
        for label, cut in cutoffs.items():
            probability = fitted[picks[label]].predict_proba(X)[:, 1]
            per_model[label] = (cut, apply_threshold(y, probability, cut), confusion_counts(y, probability, cut))
    results["oracle ceiling (true probability)"] = score(y, test[config.ORACLE])
    chosen_probability = fitted[picks["chosen"]].predict_proba(X)[:, 1]
    baseline_probability = fitted[picks[rival]].predict_proba(X)[:, 1]
    improvement = bootstrap_difference(y, chosen_probability, baseline_probability, test["patient_id"])
    return results, apply_threshold(y, chosen_probability, threshold), improvement, per_model


def run(df: pd.DataFrame | None = None, candidates: list[Candidate] = CANDIDATES,
        score_test: bool = True, cv: dict | None = None) -> TrainingResult:
    """With `cv` (fold scores per candidate), the choice is made by cross-validation (Week 4); without
    it, by validation (Week 3's rule, still used to rebuild the served release exactly)."""
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

    chosen, cv_bar = select_by_cv(cv) if cv is not None else (select(val_scores), None)
    chosen_val_probability = fitted[chosen].predict_proba(X_val)[:, 1]
    threshold_value = choose_threshold(y_val, chosen_val_probability)

    picks = {
        "floor": best_of(val_scores, family="floor"),
        "baseline": best_of(val_scores, family="baseline", cv=cv),
        "best logistic + engineered": best_of(val_scores, name="logreg_engineered", cv=cv),
        **({"best random forest": best_of(val_scores, name="random_forest", cv=cv)}
           if any(c.name == "random_forest" for c in candidates) else {}),
        "best gradient boosting": best_of(val_scores, name="gradient_boosting", cv=cv),
        "chosen": chosen,
    }
    # Week 4: every algorithm gets its own F1-best cut-off on VALIDATION, fixed before the test is scored.
    cutoffs = None if cv is None else {
        label: choose_threshold(y_val, fitted[c].predict_proba(X_val)[:, 1])
        for label, c in picks.items() if label != "floor"}
    # Week 3 asked "did the improved model beat the baseline?". In Week 4 the chosen model may BE the
    # baseline, so the question becomes "what did choosing the simplest model cost?": chosen versus the
    # best other model by CV mean, fixed here before the test set is scored.
    rival = "baseline" if cv is None else max(
        (k for k in picks if k not in ("floor", "chosen") and picks[k] != chosen),
        key=lambda k: float(np.mean(cv[picks[k]])))
    test_scores, test_threshold, improvement, per_model = (
        evaluate_on_test(fitted, picks, test, threshold_value, cutoffs, rival) if score_test else ({}, None, None, None))

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
        per_model_test=None if per_model is None else {
            ("chosen: " + chosen.label if k == "chosen" else f"{k}: {picks[k].label}"): v for k, v in per_model.items()},
        improvement=improvement,
        fitted=fitted,
        cv=cv,
        cv_bar=cv_bar,
        rival=None if cv is None else f"{rival}: {picks[rival].label}",
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


# The test set's history, stated plainly (user request; made consistent after the mentor review on PR #1).
TEST_HISTORY_NOTE = f"""**Status of these test numbers: exploratory evidence.** Two different things happened in Week 4, and
they used the test set differently:

1. **Experimental selection (sections 1–2): did not read the test set.** The model was chosen by
   cross-validation on training rows and confirmed on validation. A test flips every test label and
   checks that the choice, the cut-offs and the comparison model don't change.
2. **Release decision (section 7): test-informed.** Keeping release {FIRST_RELEASE} was decided after reading
   section 5, so that decision is not independent of these numbers.

On top of that, the same 3,952 test rows were already scored once in Week 3, for release {FIRST_RELEASE}
([release-{FIRST_RELEASE}.md](release-{FIRST_RELEASE}.md)). This test set is therefore no longer a clean estimate
for either model. The next final evaluation uses a **fresh holdout** reserved for it (`ml/holdout.py`: a
different seed, patient IDs that cannot collide), judged under the champion/challenger rule frozen in
`ml/release_rule.py` before any evaluation."""


def _per_model_section(result: TrainingResult) -> str:
    rows = []
    for label, (cut, t, c) in result.per_model_test.items():
        s = result.test[label]
        name = f"**{label}**" if label.startswith("chosen") else label
        rows.append(f"| {name} | {cut:.4f} | {c['tp']:,} | {c['fp']:,} | {c['fn']:,} | {c['tn']:,} | {t.precision:.3f} "
                    f"| {t.recall:.3f} | {t.f1:.3f} | {s.roc_auc:.3f} | {s.pr_auc:.3f} |")
    return """### Confusion matrix for each algorithm (test, each at its own validation cut-off)

Every algorithm gets its own F1-best cut-off, chosen on validation before the test set was scored, so the
comparison is fair (one shared cut-off would favour whichever model it was tuned for). TP: no-shows
flagged · FP: attenders flagged (an unneeded reminder) · FN: no-shows missed · TN: attenders not flagged.

| model | cut-off | TP | FP | FN | TN | precision | recall | F1 | ROC-AUC | PR-AUC |
|---|---|---|---|---|---|---|---|---|---|---|
""" + "\n".join(rows)


def _release_decision(result: TrainingResult) -> str:
    """Week 4 release decision (user-decided): keep serving the first release; no new release."""
    served = next(c for c in result.cv if c.label == SERVED_ESTIMATOR)
    chosen_mean = float(np.mean(result.cv[result.chosen]))
    served_mean, served_sd = float(np.mean(result.cv[served])), float(np.std(result.cv[served], ddof=1))
    se = served_sd / math.sqrt(len(result.cv[served]))
    return f"""## 7. Release decision: keep serving {config.MODEL_NAME}-{FIRST_RELEASE}

**Decision: no new release.** The served model stays `{SERVED_ESTIMATOR}` ({config.MODEL_NAME}-{FIRST_RELEASE}),
still exactly reproducible and checked in CI. The Week 4 rule's choice, `{result.chosen.label}`, is recorded
above and was not shipped.

1. **This decision is not test-independent.** It was made after section 5 showed the rule's choice scoring
   below the best other model on test. The test set therefore informed a release decision, and is no longer
   a clean estimate for the served model either.
2. **Cross-validation alone also supports it (champion/challenger).** The served model is the champion and
   the rule's choice the challenger. On the same training folds the challenger's mean was {chosen_mean:.3f}
   against the champion's {served_mean:.3f} (one standard error {se:.3f}): the challenger did not beat the
   champion by more than one standard error, so there was no evidence to replace the served model.
3. **Lesson.** The simplicity preference made sense between logistic regression and trees (readable
   weights versus hundreds of trees). Between two logistic regressions both are equally explainable, so
   preferring the one with fewer inputs bought nothing and cost accuracy. For future releases, the
   champion/challenger rule is written down before evaluation (docs/REQUIREMENTS.md)."""


def simplicity_cost_verdict(imp: Improvement) -> str:
    if imp.high < 0:
        return "the simpler choice cost accuracy on test: the whole 95% interval is below zero"
    if imp.low > 0:
        return "the simpler choice did better on test: the whole 95% interval is above zero"
    return "no clear difference on test: the 95% interval includes zero"


def _comparison_section(result: TrainingResult) -> str:
    imp = result.improvement
    interval = (f"**{imp.difference:+.3f}**, 95% interval\n**[{imp.low:+.3f}, {imp.high:+.3f}]** (bootstrap over whole "
                f"patients, {imp.resamples} resamples, seed {config.SEED}).")
    if result.rival is None:
        return f"""## 5. Did the improved model really beat the baseline?

Test PR-AUC, chosen minus baseline: {interval}

Verdict: **{imp.verdict}.**"""
    return f"""## 5. What did choosing the simplest model cost?

The cross-validation rule picked the simplest model within one standard error of the best. The question
fixed before the test was scored: how does it compare with the best other model by CV mean
(`{result.rival}`)?

Test PR-AUC, chosen minus that model: {interval}

Verdict: **{simplicity_cost_verdict(imp)}.** Reported as-is; the choice is not revisited after seeing it."""


def _test_sections(result: TrainingResult) -> tuple[str, str]:
    floor_test = next(s for k, s in result.test.items() if k.startswith("floor"))
    oracle_test = result.test["oracle ceiling (true probability)"]
    test_rows = "\n".join(_row(k, s, floor_test, oracle_test, "**" if k.startswith("chosen") else "")
                          for k, s in result.test.items())
    baseline_test = next(s for k, s in result.test.items() if k.startswith("baseline"))
    chosen_test = next(s for k, s in result.test.items() if k.startswith("chosen"))
    tt = result.test_threshold
    extra = "" if result.per_model_test is None else "\n\n" + _per_model_section(result) + "\n\n" + TEST_HISTORY_NOTE
    threshold_row = (f"| test (same threshold, applied once) | {tt.value:.4f} | {tt.precision:.3f} | {tt.recall:.3f} "
                     f"| {tt.f1:.3f} | {100 * tt.flagged_share:.1f}% |\n\n"
                     f"In words: of the appointments the model flags, about {100 * tt.precision:.0f}% are real no-shows\n"
                     f"(precision), and it catches about {100 * tt.recall:.0f}% of all no-shows (recall).")
    sections = f"""## 4. Test set: scored once, after every decision above

{HEADER}
{test_rows}

PR-AUC on test: chosen {chosen_test.pr_auc:.3f} vs baseline {baseline_test.pr_auc:.3f} vs oracle
{oracle_test.pr_auc:.3f}. Test rows were not used for tuning, model choice or the threshold.{extra}

{_comparison_section(result)}

This verdict is computed from the numbers every time the report is generated. If a change to the data
or the models ever makes the improvement disappear, the report says so; the code is not adjusted
until it passes."""
    return threshold_row, sections


COMPARISON_TITLE = "Model comparison: synthetic appointment no-shows"
RELEASE_TITLE = (f"First release {config.MODEL_NAME}-{FIRST_RELEASE}: how it was chosen and its test score\n\n"
                 "> Rebuilt from the candidates this release was chosen from (Week 3), so the served model stays\n"
                 "> exactly reproducible. The Week 4 comparison of every model is in [metrics.md](metrics.md).")


def _choice_text(result: TrainingResult, chosen_val: Scores, best_real: float) -> str:
    if result.cv is None:
        return (f"**Chosen: {result.chosen.label}** (validation PR-AUC {chosen_val.pr_auc:.3f}).\n\n"
                f"Rule, fixed before training: highest validation PR-AUC; any model within {TIE_MARGIN} of the best\n"
                f"(here {best_real:.3f}) counts as tied, and among tied models the simplest wins.")
    real = [c for c in result.validation if c.family != "floor" and c in result.cv]
    rows = "\n".join(
        f"| {'**' + c.label + '**' if c == result.chosen else c.label} | {np.mean(result.cv[c]):.3f} ± "
        f"{np.std(result.cv[c], ddof=1):.3f} | {'yes' if np.mean(result.cv[c]) >= result.cv_bar else ''} "
        f"| {result.validation[c].pr_auc:.3f} |"
        for c in sorted(real, key=lambda c: (c.complexity, c.label)))
    folds = result.cv[result.chosen]
    mean, sd = float(np.mean(folds)), float(np.std(folds, ddof=1))
    confirmed = confirmed_by_validation(folds, chosen_val.pr_auc)
    return f"""**Chosen: {result.chosen.label}** (CV PR-AUC {mean:.3f} ± {sd:.3f}; validation PR-AUC {chosen_val.pr_auc:.3f}).

Rule (Week 4, Step 3): choose by **cross-validation** on the training rows, five patient-grouped,
stratified folds ([tuning.md](tuning.md)). The bar is the best mean CV PR-AUC minus one standard error
of that mean, here **{result.cv_bar:.3f}**; every model at or above it counts as tied, and the simplest
wins. This replaced choosing by the single validation score after Step 3 showed one validation draw was
too noisy to separate close models (see docs/REQUIREMENTS.md, "Lessons").

| model | CV PR-AUC (mean ± sd) | at or above bar | validation PR-AUC |
|---|---|---|---|
{rows}

Confirmation check on validation, fixed with the rule: the chosen model's validation PR-AUC should lie
within its CV mean ± {CONFIRMATION_SDS} fold SDs ({mean - CONFIRMATION_SDS * sd:.3f} to {mean + CONFIRMATION_SDS * sd:.3f}).
Result: {chosen_val.pr_auc:.3f}, **{'confirmed' if confirmed else 'NOT confirmed: investigate before the final evaluation'}**."""


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

{_choice_text(result, chosen_val, best_real)} Simplicity order,
fixed before training: {simplicity}. Logistic regression comes first because its weights can be
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
""" + ("" if result.rival is None else "\n" + _release_decision(result) + "\n")


def comparison_run(df: pd.DataFrame | None = None) -> TrainingResult:
    """Week 4 final evaluation: every candidate, chosen by cross-validation, then the test set scored once."""
    return run(df, cv=load_cv_scores())


def comparison_report(df: pd.DataFrame | None = None) -> str:
    return build_report(comparison_run(df))


def release_report(df: pd.DataFrame | None = None) -> str:
    return build_report(run(df, candidates=RELEASE_CANDIDATES), RELEASE_TITLE)


def main():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    for path, build_text in [(REPORT, comparison_report), (RELEASE_REPORT, release_report)]:
        path.write_text(build_text())
        print(f"written to: {path}")


if __name__ == "__main__":
    main()
