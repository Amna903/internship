"""Week 4 Step 5: which inputs the models rely on, and what their mistakes have in common.

Run:  python -m ml.explain      (writes ml/reports/explain.md)

Explanation only: nothing here chooses or changes a model, and the test set is not used. Everything is
computed on VALIDATION rows.
  1. Permutation importance of the served model (release 1.0.0) on the RAW input columns: shuffle one
     input, see how much validation PR-AUC drops. Engineered features are computed from their source
     column inside the pipeline, so they move with it and each result reads as "how much does the model
     rely on this input?".
  2. Correlated inputs share credit, so the history pair (prior appointments and prior no-shows) is also
     shuffled together as a group.
  3. The random forest (best by CV): built-in impurity importance next to its permutation importance.
  4. False positives and false negatives of the served model: what each kind has in common, and how many
     were unavoidable (the true probability would have made the same call).
"""

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score

from . import config, train
from .data import generate
from .errors import error_sources
from .features import ENGINEERED_NUMERIC
from .inference import load
from .models import GRID_CANDIDATES, build
from .preprocess import model_input
from .split import split

REPORT = config.ML_DIR / "reports" / "explain.md"
REPEATS = 20
GROUPS = {"history (prior_appointments + prior_no_shows)": ["prior_appointments", "prior_no_shows"]}
# Inputs the generator weights most (ml/data.py, DATA_CARD): lead time, the patient's no-show habit (only
# visible through prior no-shows) and age band. A model that learned the formula should rank them high.
PLANTED_STRONGEST = ["lead_time_days", "prior_no_shows", "age_band"]


def importances(model, X: pd.DataFrame, y, repeats: int = REPEATS) -> dict[str, dict]:
    """Feature -> mean and sd of the PR-AUC drop over `repeats` seeded shuffles (single-threaded, exact)."""
    result = permutation_importance(model, X, y, scoring="average_precision", n_repeats=repeats,
                                    random_state=config.SEED, n_jobs=1)
    return {f: {"mean": float(m), "sd": float(s)}
            for f, m, s in zip(X.columns, result.importances_mean, result.importances_std)}


def group_importance(model, X: pd.DataFrame, y, columns: list[str], repeats: int = REPEATS) -> dict:
    """Shuffle several columns with the SAME row order: their relationship to each other stays intact,
    only their link to the label breaks. Credit they share is then counted once, for the group."""
    rng = np.random.default_rng(config.SEED)
    base = average_precision_score(y, model.predict_proba(X)[:, 1])
    drops = []
    for _ in range(repeats):
        order = rng.permutation(len(X))
        shuffled = X.copy()
        shuffled[columns] = X[columns].iloc[order].to_numpy()
        drops.append(base - average_precision_score(y, model.predict_proba(shuffled)[:, 1]))
    return {"mean": float(np.mean(drops)), "sd": float(np.std(drops))}


def impossible_share(rows: pd.DataFrame, repeats: int = REPEATS) -> float:
    """Share of rows with more prior no-shows than prior appointments after shuffling prior_no_shows alone
    (impossible in the real data): one reason single shuffles of the history pair can mislead."""
    rng = np.random.default_rng(config.SEED)
    appointments, no_shows = rows["prior_appointments"].to_numpy(), rows["prior_no_shows"].to_numpy()
    return float(np.mean([(no_shows[rng.permutation(len(rows))] > appointments).mean() for _ in range(repeats)]))


def within_noise(imp: dict) -> bool:
    """True when two standard deviations of the shuffles reach zero: no evidence the model relies on it."""
    return imp["mean"] - 2 * imp["sd"] <= 0


def source_of(encoded: str) -> str:
    """The input a model column belongs to: one-hot columns and the missing flag map to their input;
    engineered features keep their own name."""
    if encoded.startswith("missingindicator_"):
        return encoded.removeprefix("missingindicator_")
    for feature in config.CATEGORICAL_FEATURES:
        if encoded.startswith(feature + "_"):
            return feature
    return encoded


def impurity_by_input(forest_pipeline) -> dict[str, float]:
    """The forest's impurity importance, one-hot columns and the distance missing flag summed into their
    input; engineered features kept as their own rows."""
    names = forest_pipeline.named_steps["preprocess"].get_feature_names_out()
    values = forest_pipeline.named_steps["model"].feature_importances_
    out: dict[str, float] = {}
    for name, value in zip(names, values):
        out[source_of(name)] = out.get(source_of(name), 0.0) + float(value)
    return out


def profile(frame: pd.DataFrame) -> dict:
    return {"rows": len(frame), "lead_time": frame["lead_time_days"].mean(),
            "reminder": frame["reminder_sent"].mean(), "history": (frame["prior_appointments"] > 0).mean(),
            "past_rate": np.where(frame["prior_appointments"] > 0,
                                  frame["prior_no_shows"] / frame["prior_appointments"].clip(lower=1), 0).mean(),
            "young": (frame["age_band"] == "18-24").mean(), "telehealth": (frame["visit_type"] == "telehealth").mean(),
            "true_p": frame[config.ORACLE].mean()}


def analyse(df: pd.DataFrame | None = None, repeats: int = REPEATS) -> dict:
    df = generate() if df is None else df
    train_rows, validation, _ = split(df)  # the test set is not used here
    X_val, y_val = model_input(validation), validation[config.LABEL]
    served = load()
    pipeline, threshold = served.pipeline, served.threshold

    forest_candidate = train.best_of({c: None for c in GRID_CANDIDATES}, name="random_forest",
                                     cv=train.load_cv_scores(GRID_CANDIDATES))
    forest = build(forest_candidate).fit(model_input(train_rows), train_rows[config.LABEL])

    p_val = pipeline.predict_proba(X_val)[:, 1]
    flagged = p_val >= threshold
    y = y_val.to_numpy()
    kinds = {"all validation": np.ones(len(y), dtype=bool), "true positives": flagged & y,
             "false positives (attended, flagged)": flagged & ~y, "false negatives (missed, not flagged)": ~flagged & y,
             "true negatives": ~flagged & ~y}

    single = importances(pipeline, X_val, y_val, repeats)
    return {
        "served": served.metadata["model"], "estimator": served.metadata["estimator"], "threshold": threshold,
        "validation_rows": len(validation), "repeats": repeats,
        "base_pr_auc": float(average_precision_score(y_val, p_val)),
        "single": single,
        "groups": {name: {"columns": cols, **group_importance(pipeline, X_val, y_val, cols, repeats),
                          "sum_of_singles": sum(single[c]["mean"] for c in cols)} for name, cols in GROUPS.items()},
        "impossible_share": impossible_share(validation, repeats),
        "forest": forest_candidate.label,
        "forest_permutation": importances(forest, X_val, y_val, repeats),
        "forest_impurity": impurity_by_input(forest),
        "profiles": {k: profile(validation[mask]) for k, mask in kinds.items()},
        "sources": error_sources(y_val, flagged, validation[config.ORACLE], threshold),
    }


# ---------------------------------------------------------------- report

def _imp(i: dict) -> str:
    return f"{i['mean']:+.4f} ± {i['sd']:.4f}"


def _group_reading(a: dict) -> str:
    out = []
    for name, g in a["groups"].items():
        if g["mean"] > g["sum_of_singles"]:
            out.append(f"For {name}, the group drop ({g['mean']:+.4f}) is larger than the sum of the single drops "
                       f"({g['sum_of_singles']:+.4f}): the inputs were covering for each other, so each alone was "
                       "understated.")
        else:
            out.append(
                f"For {name}, the opposite happened: the group drop ({g['mean']:+.4f}) is smaller than the sum of the "
                f"single drops ({g['sum_of_singles']:+.4f}). Here the singles **overstate**. The engineered past "
                "no-show rate is built from both columns, so shuffling either one alone scrambles it, and its "
                "importance is counted in both single drops. A smaller extra effect: shuffling prior no-shows alone "
                f"creates impossible rows (more no-shows than appointments) in {100 * a['impossible_share']:.1f}% of "
                "rows, which the model never saw in training. The group drop is the cleaner estimate of how much "
                "the model relies on the patient's history.")
    return " ".join(out)


def _impurity_reading(impurity: dict, perm: dict) -> str:
    """Name the input whose impurity importance most exceeds its share of permutation importance."""
    inputs = [f for f in config.FEATURES if f in perm]
    total_impurity = sum(impurity.get(f, 0.0) for f in inputs)
    total_perm = sum(max(perm[f]["mean"], 0.0) for f in inputs)
    excess = {f: impurity.get(f, 0.0) / total_impurity - max(perm[f]["mean"], 0.0) / total_perm for f in inputs}
    worst = max(excess, key=excess.get)
    return (f"The clearest case here is `{worst}`: {impurity.get(worst, 0.0):.3f} of the impurity importance, but a "
            f"permutation drop of only {perm[worst]['mean']:+.4f}. Permutation importance is the measure to trust "
            "for reliance; impurity importance shows where the trees found split points.")


def _compare(group: dict, everyone: dict) -> str:
    """Plain-language comparison with all appointments; every direction is computed, none assumed."""
    def more_or_less(key, label_more, label_less):
        return label_more if group[key] > everyone[key] else label_less
    return (f"booked {group['lead_time']:.1f} days ahead on average (all: {everyone['lead_time']:.1f}); "
            f"{more_or_less('reminder', 'more', 'less')} often reminded ({100 * group['reminder']:.1f}% vs "
            f"{100 * everyone['reminder']:.1f}%); {more_or_less('young', 'more', 'less')} often aged 18–24 "
            f"({100 * group['young']:.1f}% vs {100 * everyone['young']:.1f}%); past no-show rate "
            f"{100 * group['past_rate']:.1f}% (all: {100 * everyone['past_rate']:.1f}%). Their true no-show "
            f"probability averages {100 * group['true_p']:.1f}% (all: {100 * everyone['true_p']:.1f}%), so "
            + ("the model's call was reasonable: they looked like no-shows and attended anyway."
               if group["true_p"] > everyone["true_p"] else
               "these no-shows were less likely than average: they looked like attenders and missed anyway."))


def build_report(a: dict) -> str:
    single = a["single"]
    ranked = sorted(single, key=lambda f: -single[f]["mean"])
    single_rows = "\n".join(f"| `{f}` | {_imp(single[f])} | {'within noise' if within_noise(single[f]) else ''} |"
                            for f in ranked)
    top = set(ranked[:len(PLANTED_STRONGEST) + 1])
    planted_found = [f for f in PLANTED_STRONGEST if f in top]
    group_rows = "\n".join(f"| {name} | {_imp(g)} | {g['sum_of_singles']:+.4f} |" for name, g in a["groups"].items())

    # Forest rows in a FIXED order (inputs, then engineered features): forest numbers differ slightly between
    # machines, and sorting by value could reorder near-equal rows.
    impurity, forest_perm = a["forest_impurity"], a["forest_permutation"]
    forest_rows = "\n".join(
        f"| `{f}` | {impurity.get(f, 0.0):.3f} | {_imp(forest_perm[f]) if f in forest_perm else 'moves with its source'} |"
        for f in config.FEATURES + ENGINEERED_NUMERIC if f in impurity or f in forest_perm)
    continuous = ["lead_time_days", "distance_km", "appointment_hour"]
    impurity_share = sum(impurity.get(f, 0.0) for f in continuous)

    p = a["profiles"]
    profile_rows = "\n".join(
        f"| {k} | {v['rows']:,} | {v['lead_time']:.1f} | {100 * v['reminder']:.1f}% | {100 * v['history']:.1f}% | "
        f"{100 * v['past_rate']:.1f}% | {100 * v['young']:.1f}% | {100 * v['telehealth']:.1f}% | {100 * v['true_p']:.1f}% |"
        for k, v in p.items())
    s = a["sources"]
    fp, fn = p["false positives (attended, flagged)"], p["false negatives (missed, not flagged)"]

    return f"""# Explaining the models: importance and mistakes

> Synthetic, educational data. Generated by `python -m ml.explain`; do not edit by hand. Explanation only:
> nothing here changes a model, and the test set is not used. Everything is on the {a['validation_rows']:,}
> validation rows. Importance measures what a model relies on, not what causes no-shows.

Served model: `{a['served']}` ({a['estimator']}), validation PR-AUC {a['base_pr_auc']:.3f}.

## 1. Permutation importance of the served model

Each input is shuffled {a['repeats']} times (seed {config.SEED}); the column shows how much validation PR-AUC drops
(mean ± sd over the shuffles). Engineered features (log lead time, past no-show rate, reminder × lead
time) are computed from their input inside the pipeline, so they move with it. "Within noise": two
standard deviations reach zero, so there is no evidence the model relies on that input.

| input | PR-AUC drop when shuffled | |
|---|---|---|
{single_rows}

The generator weights lead time, the no-show habit (visible only through prior no-shows) and age band
most. Of these, {len(planted_found)} of {len(PLANTED_STRONGEST)} rank in the top {len(PLANTED_STRONGEST) + 1}:
{', '.join(f'`{f}`' for f in planted_found) or 'none'}.

`age_band` appears here because age is a planted driver of no-shows in this synthetic data. Relying on it
makes the model flag younger patients more often, including some who would attend; that cost is measured
in [errors.md](errors.md) (age bias section).

### Caveat: correlated inputs share credit

Inputs that carry overlapping information can share credit: when one is shuffled, the model still gets
part of the same signal from the other, so shuffling one alone may **understate** its importance. Prior
appointments and prior no-shows are such a pair (the no-show rate is built from both). Shuffling them
**together**, with the same row order so their relationship stays intact, counts their shared credit once:

| group | PR-AUC drop, shuffled together | sum of the two shuffled alone |
|---|---|---|
{group_rows}

{_group_reading(a)}

## 2. Random forest: impurity importance versus permutation importance

The random forest with the best CV score (`{a['forest']}`), refitted on the train part. **Impurity
importance** (built in) measures how much each input's splits reduce impurity while training; one-hot
columns are summed into their input. **Permutation importance** is computed as in section 1.

| input | impurity importance (sums to 1) | permutation: PR-AUC drop |
|---|---|---|
{forest_rows}

Known flaw: impurity importance favours inputs with many distinct values, because they offer more
split points even when the splits fit noise. The three continuous inputs (lead time, distance, hour)
hold {100 * impurity_share:.0f}% of the forest's impurity importance. {_impurity_reading(impurity, forest_perm)}

## 3. False positives and false negatives of the served model

At the served cut-off ({a['threshold']:.4f}): what each kind of appointment has in common, compared with
all validation appointments.

| | rows | mean lead time (days) | reminder sent | has history | past no-show rate | age 18–24 | telehealth | true no-show probability |
|---|---|---|---|---|---|---|---|---|
{profile_rows}

- **False positives** (attended but flagged, an unneeded reminder): {_compare(fp, p['all validation'])}
- **False negatives** (missed but not flagged): {_compare(fn, p['all validation'])}

Unavoidable or model mistake? The synthetic data has the true probability, so we can ask whether perfect
knowledge, with the same cut-off, would have made the same call:

| | errors | unavoidable (true probability makes the same call) | model mistakes |
|---|---|---|---|
| false positives | {s['fp']:,} | {s['fp_unavoidable']:,} ({100 * s['fp_unavoidable'] / s['fp']:.0f}%) | {s['fp'] - s['fp_unavoidable']:,} |
| false negatives | {s['fn']:,} | {s['fn_unavoidable']:,} ({100 * s['fn_unavoidable'] / s['fn']:.0f}%) | {s['fn'] - s['fn_unavoidable']:,} |

The five most confident mistakes of each kind, with their inputs, are listed in [errors.md](errors.md).
"""


def main():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(analyse()))
    print(f"written to: {REPORT}")


if __name__ == "__main__":
    main()
