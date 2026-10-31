"""Week 4 Step 3: stratified, patient-grouped cross-validation and one tuning experiment, on TRAIN rows only.

Run:  python -m ml.tune      (writes ml/reports/tuning.md and ml/reports/tuning.json)

What it does, and why:
  1. Splits the TRAIN part into 5 folds with StratifiedGroupKFold: every patient's appointments stay in
     one fold (as in the main split), and each fold keeps about the same no-show rate.
  2. Cross-validates every Step 2 candidate on those folds. One validation score is a single draw; five
     fold scores show how much a score moves by chance, so we can tell whether a lead is bigger than noise.
  3. Tunes the random forest with RandomizedSearchCV (30 seeded draws from a fixed space, same folds,
     PR-AUC) and picks a setting with the one-standard-error rule below.
Validation and test rows are never passed to anything here. The tuned forest then competes with every
other model on validation in `ml.train`, under the same rule as Step 2.

Rules, fixed before the search runs:
  - One-standard-error rule: the best mean CV PR-AUC minus one standard error of that mean is the bar.
    Every setting at or above it is treated as tied (its lead could be fold noise), and the SIMPLEST of
    them wins: shallower trees, then larger leaves, then fewer columns per split, then MORE trees
    (`Candidate.within_family_simplicity`; tree count steadies the vote and doesn't cause overfitting).
"""

import json
import math

import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.metrics import average_precision_score
from sklearn.model_selection import RandomizedSearchCV, StratifiedGroupKFold

from . import config
from .data import generate
from .models import GRID_CANDIDATES, RF_TREES, Candidate, build
from .preprocess import model_input
from .split import split

REPORT = config.ML_DIR / "reports" / "tuning.md"
RESULT = config.ML_DIR / "reports" / "tuning.json"

N_SPLITS = 5
N_ITER = 30
SEARCH_SPACE = {
    "max_depth": [4, 6, 8, 10, 14, None],
    "min_samples_leaf": [10, 20, 50, 100, 200],
    "max_features": ["sqrt", 0.33, 0.5, 1.0],
    "n_estimators": [100, 200, 300, 500],
}


def make_folds(train: pd.DataFrame, n_splits: int = N_SPLITS) -> list[tuple[np.ndarray, np.ndarray]]:
    """Row positions (into `train`) of each fold's fitting and scoring rows."""
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=config.SEED)
    return list(splitter.split(train, train[config.LABEL], groups=train["patient_id"]))


def fold_table(train: pd.DataFrame, folds) -> list[dict]:
    return [{"fold": i + 1, "rows": len(scored), "patients": int(train.iloc[scored]["patient_id"].nunique()),
             "no_show_rate": float(train.iloc[scored][config.LABEL].mean())}
            for i, (_, scored) in enumerate(folds)]


def _fold_score(candidate: Candidate, X: pd.DataFrame, y: pd.Series, fit_rows, scored_rows) -> float:
    model = build(candidate).fit(X.iloc[fit_rows], y.iloc[fit_rows])
    return float(average_precision_score(y.iloc[scored_rows], model.predict_proba(X.iloc[scored_rows])[:, 1]))


def cross_validate(candidates: list[Candidate], train: pd.DataFrame, folds) -> dict:
    """Candidate -> list of fold PR-AUCs. Each fit is independent and single-threaded, so running them
    in parallel gives exactly the same numbers as running them one by one."""
    X, y = model_input(train), train[config.LABEL]
    jobs = [(c, fit_rows, scored_rows) for c in candidates for fit_rows, scored_rows in folds]
    scores = Parallel(n_jobs=-1)(delayed(_fold_score)(c, X, y, f, s) for c, f, s in jobs)
    out: dict = {c: [] for c in candidates}
    for (c, _, _), s in zip(jobs, scores):
        out[c].append(s)
    return out


def forest(params: dict) -> Candidate:
    """A random-forest Candidate with every searched setting spelled out (fixed key order)."""
    return Candidate("improved", "random_forest", engineered=True,
                     params=tuple((k, params[k]) for k in SEARCH_SPACE), complexity=2)


def search(train: pd.DataFrame, folds, n_iter: int = N_ITER, space: dict = SEARCH_SPACE) -> list[dict]:
    """RandomizedSearchCV over the forest's settings, scored by PR-AUC on the given folds.
    refit=False: the search only ranks settings; the chosen one is fitted on the whole train part later."""
    base = forest({"max_depth": None, "min_samples_leaf": 1, "max_features": "sqrt", "n_estimators": RF_TREES})
    searcher = RandomizedSearchCV(
        build(base), {f"model__{k}": v for k, v in space.items()}, n_iter=n_iter, scoring="average_precision",
        cv=folds, refit=False, random_state=config.SEED, n_jobs=-1,
    )
    searcher.fit(model_input(train), train[config.LABEL])
    cv = searcher.cv_results_
    n_folds = len(folds)
    rows = []
    for i, params in enumerate(cv["params"]):
        fold_scores = [float(cv[f"split{k}_test_score"][i]) for k in range(n_folds)]
        rows.append({"params": {k: params[f"model__{k}"] for k in space}, "fold_scores": fold_scores,
                     "mean": float(np.mean(fold_scores)), "std": float(np.std(fold_scores, ddof=1))})
    return rows


def one_standard_error_pick(rows: list[dict]) -> tuple[dict, float]:
    """The simplest setting whose mean is at least (best mean - one standard error of the best mean)."""
    best = max(rows, key=lambda r: r["mean"])
    bar = best["mean"] - best["std"] / math.sqrt(len(best["fold_scores"]))
    eligible = [r for r in rows if r["mean"] >= bar]
    return min(eligible, key=lambda r: forest(r["params"]).within_family_simplicity), bar


def run(df: pd.DataFrame | None = None, n_iter: int = N_ITER, n_splits: int = N_SPLITS,
        grid: list[Candidate] = GRID_CANDIDATES) -> dict:
    df = generate() if df is None else df
    train_rows = split(df)[0]  # validation and test are never used here
    folds = make_folds(train_rows, n_splits)
    grid_cv = cross_validate(grid, train_rows, folds)
    rows = search(train_rows, folds, n_iter)
    pick, bar = one_standard_error_pick(rows)
    return {
        "seed": config.SEED, "n_splits": n_splits, "n_iter": n_iter,
        "train_rows": len(train_rows), "folds": fold_table(train_rows, folds),
        "grid_cv": [{"label": c.label, "name": c.name, "params": dict(c.params), "fold_scores": s,
                     "mean": float(np.mean(s)), "std": float(np.std(s, ddof=1))} for c, s in grid_cv.items()],
        "search_space": SEARCH_SPACE, "search": rows, "bar": bar, "chosen": pick["params"],
    }


# ---------------------------------------------------------------- report

def _ms(mean: float, std: float) -> str:
    return f"{mean:.3f} ± {std:.3f}"


def _settings(params: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in params.items())


def build_report(result: dict, validation: dict[str, float]) -> str:
    """`validation`: Step 2 validation PR-AUC by candidate label, for the CV-versus-validation column."""
    n = result["n_splits"]
    fold_rows = "\n".join(f"| {f['fold']} | {f['rows']:,} | {f['patients']:,} | {100 * f['no_show_rate']:.2f}% |"
                          for f in result["folds"])
    rates = [f["no_show_rate"] for f in result["folds"]]
    grid = [g for g in result["grid_cv"] if g["name"] != "floor_dummy"]
    grid_rows = "\n".join(f"| {g['label']} | {_ms(g['mean'], g['std'])} | {validation[g['label']]:.3f} |"
                          for g in grid)
    by_label = {g["label"]: g for g in result["grid_cv"]}
    best_forest = max((g for g in grid if g["name"] == "random_forest"), key=lambda g: validation[g["label"]])
    best_logreg = max((g for g in grid if g["name"] == "logreg_engineered"), key=lambda g: validation[g["label"]])
    paired = np.subtract(best_forest["fold_scores"], best_logreg["fold_scores"])
    lead_mean, lead_sd = float(paired.mean()), float(paired.std(ddof=1))
    folds_ahead = int((paired > 0).sum())
    if abs(lead_mean) <= lead_sd:
        verdict = ("The difference is no larger than the fold-to-fold noise, so neither model is clearly better; "
                   "validation and the simplicity rule decide, as written.")
    elif lead_mean > 0:
        verdict = "The forest's lead is larger than the fold-to-fold noise: it is consistently better."
    else:
        verdict = ("Logistic regression's lead is larger than the fold-to-fold noise: it is consistently better, "
                   "so the forest's Step 2 validation lead came from the luck of that one validation draw.")
    noise_sentence = (f"the forest is ahead in {folds_ahead} of {n} folds, by {lead_mean:+.3f} on average "
                      f"(fold-to-fold spread of that difference: {lead_sd:.3f}). {verdict}")

    ranked = sorted(result["search"], key=lambda r: -r["mean"])
    chosen = result["chosen"]
    search_rows = "\n".join(
        f"| {i + 1} | {_settings(r['params'])} | {_ms(r['mean'], r['std'])} | "
        f"{'yes' if r['mean'] >= result['bar'] else ''} | {'**chosen**' if r['params'] == chosen else ''} |"
        for i, r in enumerate(ranked[:10]))
    eligible = sum(r["mean"] >= result["bar"] for r in ranked)
    best = ranked[0]
    chosen_row = next(r for r in ranked if r["params"] == chosen)
    space = "\n".join(f"| `{k}` | {', '.join(str(v) for v in vs)} |" for k, vs in result["search_space"].items())

    return f"""# Cross-validation and tuning (training rows only)

> Synthetic, educational data. Generated by `python -m ml.tune`; do not edit by hand. Validation and test
> rows are never used here. The tuned forest is compared with every other model on validation in
> [metrics.md](metrics.md).

| | |
|---|---|
| Rows used | {result['train_rows']:,} (the train part only) |
| Folds | {n}, `StratifiedGroupKFold` (patients kept whole, no-show rate balanced), seed {result['seed']} |
| Metric | PR-AUC, mean ± standard deviation across folds |

## 1. Folds

| fold | rows | patients | no-show rate |
|---|---|---|---|
{fold_rows}

No patient is in two folds. No-show rates range from {100 * min(rates):.2f}% to {100 * max(rates):.2f}%.

## 2. Cross-validation of every Step 2 model

One validation score is one draw. The fold spread shows how far a score moves by chance alone.

| model | CV PR-AUC (mean ± sd) | Step 2 validation PR-AUC |
|---|---|---|
{grid_rows}

Is the forest's lead over logistic regression real? Comparing the best of each on the same folds
(`{best_forest['label']}` vs `{best_logreg['label']}`): {noise_sentence}

## 3. Tuning experiment: random forest, `RandomizedSearchCV`

{result['n_iter']} settings drawn (seed {result['seed']}) from this space, each scored on the same {n} folds:

| setting | values |
|---|---|
{space}

Rule, fixed before the search ran (**one-standard-error rule**): the bar is the best mean minus one
standard error of that mean, here {best['mean']:.3f} − {best['std']:.3f}/√{n} = **{result['bar']:.3f}**.
Every setting at or above the bar counts as tied, because its lead could be fold noise, and the
**simplest** of them wins: shallower trees, then larger leaves, then fewer columns per split, then
**more** trees (more trees only steady the vote; they don't cause overfitting).

Top 10 of {result['n_iter']} by mean CV PR-AUC ({eligible} settings reached the bar):

| rank | settings | CV PR-AUC | at or above bar | |
|---|---|---|---|---|
{search_rows}

**Chosen: {_settings(chosen)}**, CV PR-AUC {_ms(chosen_row['mean'], chosen_row['std'])}
(the top-scoring setting had {_ms(best['mean'], best['std'])}).

For comparison, the Step 2 grid's best forest (`{best_forest['label']}`) scored
{_ms(by_label[best_forest['label']]['mean'], by_label[best_forest['label']]['std'])} on the same folds.

## 4. What this shows

- Fold-to-fold spread is about {np.median([g['std'] for g in grid]):.3f} PR-AUC for a typical model, larger than most gaps
  between the Step 2 models. A single validation score can't separate them reliably; that is why ties
  are resolved by simplicity rather than by the last digit.
- The search only ranked settings on training folds. The chosen forest is then fitted on the whole train
  part and judged on validation with everything else, so the tuning can't overfit the validation set.
"""


def main():
    from . import train

    result = run()
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, indent=2) + "\n")
    step2 = train.run(candidates=GRID_CANDIDATES, score_test=False)
    validation = {c.label: s.pr_auc for c, s in step2.validation.items()}
    REPORT.write_text(build_report(result, validation))
    print(f"written to: {RESULT}\nwritten to: {REPORT}")


if __name__ == "__main__":
    main()
