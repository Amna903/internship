"""Error analysis of the chosen model: who it gets wrong, whether its probabilities can be trusted,
how it treats age groups, and whether it learned the planted formula.

Run:  python -m ml.errors      (writes ml/reports/errors.md)

Rules:
  * Analysis is done on VALIDATION. The test set already had its single scoring in Step 4; test
    numbers appear here for reporting only.
  * Nothing in this file changes the shipped model. The model and threshold come from Step 4. If
    an analysis suggests a change (recalibration, dropping age), it is reported as a finding and a
    possible next step: changing the model now would make the Step 4 test score describe a model
    that is no longer the one shipped.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from . import config, train
from .data import generate
from .eda import lead_time_bucket
from .models import RELEASE_CANDIDATES, build
from .preprocess import model_input
from .split import split

REPORT = config.ML_DIR / "reports" / "errors.md"
CALIBRATION_BINS = 10
FAMILY_ALPHA = 0.05  # overall false-alarm rate allowed across ALL calibration bins together
# Bonferroni: each of the 10 bins is tested at 0.05/10, i.e. |z| > 2.81 (two-sided). A plain 2-SE rule
# per bin would raise at least one false alarm ~40% of the time even for a perfectly calibrated model.
CALIBRATION_Z_LIMIT = math.sqrt(2) * float(
    __import__("scipy.special", fromlist=["erfcinv"]).erfcinv(FAMILY_ALPHA / CALIBRATION_BINS)
)


# ---------------------------------------------------------------- building blocks (pure, unit-tested)


def confusion(y, flagged) -> dict:
    y, flagged = np.asarray(y, dtype=bool), np.asarray(flagged, dtype=bool)
    return {
        "tp": int((flagged & y).sum()),
        "fp": int((flagged & ~y).sum()),
        "fn": int((~flagged & y).sum()),
        "tn": int((~flagged & ~y).sum()),
    }


def rates(c: dict) -> dict:
    positives, negatives = c["tp"] + c["fn"], c["fp"] + c["tn"]
    flagged, total = c["tp"] + c["fp"], sum(c.values())
    return {
        "fpr": c["fp"] / negatives if negatives else float("nan"),  # attenders wrongly flagged
        "fnr": c["fn"] / positives if positives else float("nan"),  # no-shows missed
        "recall": c["tp"] / positives if positives else float("nan"),
        "precision": c["tp"] / flagged if flagged else float("nan"),
        "flag_rate": flagged / total if total else float("nan"),
    }


def calibration_table(y, probability, bins: int = CALIBRATION_BINS) -> pd.DataFrame:
    """Equal-size bins by predicted probability: predicted vs observed rate, with a sampling-noise check."""
    frame = pd.DataFrame({"y": np.asarray(y, dtype=float), "p": np.asarray(probability, dtype=float)})
    frame["bin"] = pd.qcut(frame["p"].rank(method="first"), bins, labels=False)
    table = frame.groupby("bin").agg(n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean"))
    table["gap"] = table["observed"] - table["predicted"]
    # If the model were calibrated, the observed rate in a bin would vary around the predicted rate
    # with this standard error, purely from sampling.
    table["se"] = np.sqrt(table["predicted"] * (1 - table["predicted"]) / table["n"])
    table["z"] = table["gap"] / table["se"]
    table["flagged"] = table["z"].abs() > CALIBRATION_Z_LIMIT
    return table


def expected_calibration_error(table: pd.DataFrame) -> float:
    """Row-weighted average |observed - predicted| across bins."""
    return float((table["n"] * table["gap"].abs()).sum() / table["n"].sum())


def group_table(y, flagged, probability, groups, order=None) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "y": np.asarray(y, dtype=bool),
            "f": np.asarray(flagged, dtype=bool),
            "p": np.asarray(probability, dtype=float),
            "g": np.asarray(groups),
        }
    )
    rows = {}
    for group, part in frame.groupby("g", observed=True, sort=False):
        r = rates(confusion(part["y"], part["f"]))
        rows[group] = {"rows": len(part), "no_show_rate": part["y"].mean(), "mean_prediction": part["p"].mean(), **r}
    table = pd.DataFrame.from_dict(rows, orient="index")
    return table.reindex(order) if order is not None else table.sort_index()


def fairness_gaps(table: pd.DataFrame, a, b) -> dict:
    """Differences between two groups of a group_table (a minus b)."""
    return {
        "fpr_gap": table.loc[a, "fpr"] - table.loc[b, "fpr"],
        "recall_gap": table.loc[a, "recall"] - table.loc[b, "recall"],  # "equal opportunity"
        "flag_rate_ratio": table.loc[a, "flag_rate"] / table.loc[b, "flag_rate"],
    }


def error_sources(y, flagged, true_probability, threshold) -> dict:
    """Synthetic data lets us ask: would a model with PERFECT knowledge of the true probability, using
    the same threshold, have made the same mistake? If yes, the error is the coin flip's fault."""
    y, flagged = np.asarray(y, dtype=bool), np.asarray(flagged, dtype=bool)
    oracle_flag = np.asarray(true_probability) >= threshold
    fn, fp = ~flagged & y, flagged & ~y
    return {
        "fn": int(fn.sum()),
        "fn_unavoidable": int((fn & ~oracle_flag).sum()),
        "fp": int(fp.sum()),
        "fp_unavoidable": int((fp & oracle_flag).sum()),
    }


# Planted directions from ml/data.py. For each, two versions of the same rows that differ only in
# that input; the model's average predicted probability must move in the planted direction.
PLANTED_EFFECTS = [
    ("lead time 30 vs 2 days", +1, {"lead_time_days": 30}, {"lead_time_days": 2}),
    ("reminder sent vs not", -1, {"reminder_sent": True}, {"reminder_sent": False}),
    ("age 18-24 vs 55-64", +1, {"age_band": "18-24"}, {"age_band": "55-64"}),
    ("telehealth vs in person", -1, {"visit_type": "telehealth"}, {"visit_type": "in_person"}),
    ("distance 30 vs 5 km", +1, {"distance_km": 30.0}, {"distance_km": 5.0}),
    (
        "past no-shows 2 of 4 vs 0 of 4",
        +1,
        {"prior_appointments": 4, "prior_no_shows": 2},
        {"prior_appointments": 4, "prior_no_shows": 0},
    ),
    ("friday vs tuesday", +1, {"appointment_weekday": "friday"}, {"appointment_weekday": "tuesday"}),
    ("phone vs web booking", -1, {"booking_channel": "phone"}, {"booking_channel": "web"}),
]


def effect_directions(pipeline, X: pd.DataFrame) -> list[dict]:
    """Average change in predicted probability when only one input changes (others kept as they are).
    Unlike raw coefficients, this stays meaningful when features overlap (lead time appears raw, as
    log, and inside the reminder interaction)."""
    results = []
    for name, planted_sign, high, low in PLANTED_EFFECTS:
        change = (pipeline.predict_proba(X.assign(**high))[:, 1] - pipeline.predict_proba(X.assign(**low))[:, 1]).mean()
        results.append(
            {
                "effect": name,
                "planted": planted_sign,
                "change": float(change),
                "matches": bool(np.sign(change) == planted_sign),
            }
        )
    return results


def coefficients(pipeline) -> pd.Series:
    names = pipeline.named_steps["preprocess"].get_feature_names_out()
    return pd.Series(pipeline.named_steps["model"].coef_[0], index=names)


# ---------------------------------------------------------------- the analysis


@dataclass
class Analysis:
    model_label: str
    threshold: float
    validation_rows: int
    val_confusion: dict
    test_confusion: dict
    calibration: pd.DataFrame
    ece: float
    groups: dict  # name -> group_table (validation)
    test_age: pd.DataFrame
    age_gaps: dict
    sources: dict
    directions: list
    coefs: pd.Series
    without_age: dict
    confident_fp: pd.DataFrame
    confident_fn: pd.DataFrame


def analyse(df: pd.DataFrame | None = None) -> Analysis:
    df = generate() if df is None else df
    result = train.run(df, candidates=RELEASE_CANDIDATES)
    pipeline, threshold = result.chosen_pipeline, result.threshold.value
    train_rows, validation, test = split(df)
    X_val, y_val = model_input(validation), validation[config.LABEL]
    p_val = pipeline.predict_proba(X_val)[:, 1]
    flagged = p_val >= threshold

    calibration = calibration_table(y_val, p_val)
    has_history = np.where(validation["prior_appointments"] > 0, "returning", "new patient")
    groups = {
        "age band": group_table(y_val, flagged, p_val, validation["age_band"], config.AGE_BANDS),
        "lead time (days ahead)": group_table(
            y_val,
            flagged,
            p_val,
            lead_time_bucket(validation["lead_time_days"]).astype(str),
            ["0–2", "3–7", "8–14", "15–30", "31+"],
        ),
        "reminder sent": group_table(y_val, flagged, p_val, validation["reminder_sent"], [True, False]),
        "visit type": group_table(y_val, flagged, p_val, validation["visit_type"], config.VISIT_TYPES),
        "booking channel": group_table(y_val, flagged, p_val, validation["booking_channel"], config.BOOKING_CHANNELS),
        "history": group_table(y_val, flagged, p_val, has_history, ["new patient", "returning"]),
    }

    # Mitigation (a), analysis only: the same model with age made uninformative (one constant value),
    # fitted on train and judged on validation. It is NOT shipped (see module docstring).
    neutral = {"age_band": "35-44"}
    no_age = build(result.chosen).fit(model_input(train_rows).assign(**neutral), train_rows[config.LABEL])
    p_no_age = no_age.predict_proba(X_val.assign(**neutral))[:, 1]
    no_age_table = group_table(
        y_val, p_no_age >= train.choose_threshold(y_val, p_no_age), p_no_age, validation["age_band"], config.AGE_BANDS
    )
    without_age = {
        "pr_auc_with": float(average_precision_score(y_val, p_val)),
        "pr_auc_without": float(average_precision_score(y_val, p_no_age)),
        "gaps_without": fairness_gaps(no_age_table, "18-24", "55-64"),
    }

    errors_frame = validation.assign(probability=p_val)
    show = [
        "probability",
        config.ORACLE,
        "lead_time_days",
        "reminder_sent",
        "age_band",
        "visit_type",
        "prior_appointments",
        "prior_no_shows",
        "distance_km",
    ]
    confident_fp = errors_frame[flagged & ~y_val.to_numpy()].nlargest(5, "probability")[show]
    confident_fn = errors_frame[~flagged & y_val.to_numpy()].nsmallest(5, "probability")[show]

    # Test set: reporting only (no decision below reads it).
    p_test = pipeline.predict_proba(model_input(test))[:, 1]
    test_flagged = p_test >= threshold
    test_age = group_table(test[config.LABEL], test_flagged, p_test, test["age_band"], config.AGE_BANDS)

    return Analysis(
        model_label=result.chosen.label,
        threshold=threshold,
        validation_rows=len(validation),
        val_confusion=confusion(y_val, flagged),
        test_confusion=confusion(test[config.LABEL], test_flagged),
        calibration=calibration,
        ece=expected_calibration_error(calibration),
        groups=groups,
        test_age=test_age,
        age_gaps=fairness_gaps(groups["age band"], "18-24", "55-64"),
        sources=error_sources(y_val, flagged, validation[config.ORACLE], threshold),
        directions=effect_directions(pipeline, X_val),
        coefs=coefficients(pipeline),
        without_age=without_age,
        confident_fp=confident_fp,
        confident_fn=confident_fn,
    )


# ---------------------------------------------------------------- report


def _p(x: float) -> str:
    return f"{100 * x:.1f}%"


def _group_md(table: pd.DataFrame, label: str) -> str:
    lines = [
        f"| {label} | rows | no-show rate | mean prediction | flagged | false-positive rate | false-negative rate | precision |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for group, r in table.iterrows():
        lines.append(
            f"| {group} | {int(r['rows']):,} | {_p(r['no_show_rate'])} | {_p(r['mean_prediction'])} | "
            f"{_p(r['flag_rate'])} | {_p(r['fpr'])} | {_p(r['fnr'])} | {_p(r['precision'])} |"
        )
    return "\n".join(lines)


def _widest(table: pd.DataFrame, column: str) -> str:
    return (
        f"widest {column.upper() if len(column) <= 3 else column} gap: {table[column].idxmax()} "
        f"{_p(table[column].max())} vs {table[column].idxmin()} {_p(table[column].min())}"
    )


def calibration_verdict(table: pd.DataFrame) -> str:
    flagged = int(table["flagged"].sum())
    naive = [str(int(b) + 1) for b in table.index[table["z"].abs() > 2]]
    naive_note = (
        f" A naive per-bin 2-se rule would have flagged bin(s) {', '.join(naive)}: exactly the kind of "
        "false alarm the adjusted limit exists to prevent."
        if naive and flagged == 0
        else ""
    )
    if flagged == 0:
        return (
            f"**No recalibration needed.** No bin's gap exceeds the noise limit (|z| ≤ {CALIBRATION_Z_LIMIT:.2f} "
            f"in every bin; largest |z| = {table['z'].abs().max():.2f})." + naive_note
        )
    return (
        f"**Finding: {flagged} bin(s) exceed the noise limit.** Recalibration (e.g. `CalibratedClassifierCV`) "
        "would be the next step. It is NOT applied here: the test set was already used in Step 4, and "
        "changing the model now would make that score describe a different model than the one shipped."
    )


def build_report(a: Analysis) -> str:
    c, ct = a.val_confusion, a.test_confusion
    r = rates(c)
    cal_rows = "\n".join(
        f"| {int(b) + 1} | {int(row['n'])} | {_p(row['predicted'])} | {_p(row['observed'])} | {100 * row['gap']:+.1f} pts "
        f"| {100 * row['se']:.1f} pts | {row['z']:+.2f} | {'⚠️' if row['flagged'] else 'ok'} |"
        for b, row in a.calibration.iterrows()
    )
    group_sections = "\n\n".join(
        f"### {name}\n\n{_group_md(table, name)}\n\n{_widest(table, 'fpr')}; {_widest(table, 'fnr')}."
        for name, table in a.groups.items()
    )
    g, w = a.age_gaps, a.without_age
    gw = w["gaps_without"]
    s = a.sources
    direction_rows = "\n".join(
        f"| {d['effect']} | {'↑ more no-shows' if d['planted'] > 0 else '↓ fewer no-shows'} | {100 * d['change']:+.2f} pts "
        f"| {'✅ matches' if d['matches'] else '❌ finding: opposite direction'} |"
        for d in a.directions
    )
    all_match = all(d["matches"] for d in a.directions)
    coef_rows = "\n".join(
        f"| `{name}` | {value:+.3f} |" for name, value in a.coefs.sort_values(key=abs, ascending=False).items()
    )

    def mistakes(frame):
        header = "| probability | true probability | lead time | reminder | age | visit | prior | no-shows | distance |\n|---|---|---|---|---|---|---|---|---|"
        return (
            header
            + "\n"
            + "\n".join(
                f"| {_p(row['probability'])} | {_p(row[config.ORACLE])} | {int(row['lead_time_days'])} d | "
                f"{'yes' if row['reminder_sent'] else 'no'} | {row['age_band']} | {row['visit_type']} | "
                f"{int(row['prior_appointments'])} | {int(row['prior_no_shows'])} | "
                f"{'—' if pd.isna(row['distance_km']) else f'{row["distance_km"]:.1f} km'} |"
                for _, row in frame.iterrows()
            )
        )

    return f"""# Error analysis: chosen no-show model

> Synthetic, educational data. Generated by `python -m ml.errors`; do not edit by hand.
> Model and threshold come from Step 4 ([metrics.md](metrics.md)) and are **not changed here**.
> Analysis uses the **validation** set ({a.validation_rows:,} rows). Test numbers are for reporting only.

Model: **{a.model_label}** · decision threshold **{a.threshold:.4f}** (flag for an extra reminder)

## 1. The four outcomes

| | missed (no-show) | attended |
|---|---|---|
| **flagged** | {c["tp"]:,} true positives | {c["fp"]:,} false positives |
| **not flagged** | {c["fn"]:,} false negatives | {c["tn"]:,} true negatives |

Validation: precision {_p(r["precision"])} · recall {_p(r["recall"])} · false-positive rate {_p(r["fpr"])} ·
flagged {_p(r["flag_rate"])}. Test (reporting only): {ct["tp"]:,} TP · {ct["fp"]:,} FP · {ct["fn"]:,} FN · {ct["tn"]:,} TN.

What each error costs here:
- **False positive** (flagged, attended anyway): one unnecessary reminder message. Cheap.
- **False negative** (not flagged, then missed): no extra reminder for someone who needed it; a lost slot.
  Costlier.
That cost difference is why a threshold with modest precision and higher recall is acceptable for this
use, and why the output must never drive anything costly for the patient.

## 2. Calibration: can the probabilities be trusted?

Validation rows split into {CALIBRATION_BINS} equal-size bins by predicted probability. If the model is calibrated,
each bin's observed rate differs from its predicted rate only by sampling noise (standard error, "se").
A bin is flagged only if |z| = |gap| / se exceeds **{CALIBRATION_Z_LIMIT:.2f}**: the Bonferroni limit that keeps the
chance of *any* false alarm across all {CALIBRATION_BINS} bins at {FAMILY_ALPHA:.0%}. (A plain 2-se rule per bin would raise
at least one false alarm about 40% of the time even for a perfect model.)

| bin | rows | predicted | observed | gap | se | z | |
|---|---|---|---|---|---|---|---|
{cal_rows}

Expected calibration error (row-weighted mean |gap|): **{100 * a.ece:.2f} points**.

{calibration_verdict(a.calibration)}

## 3. Errors per group (validation)

{group_sections}

Why the big gaps: false-positive rates rise wherever the model's predicted risk rises (long lead times,
young patients, no reminder), because those groups really do miss more often, so more of their attenders
also cross the threshold. This follows from the planted drivers in the EDA, not from a bug.

## 4. Bias: age

| | 18-24 | 55-64 | gap |
|---|---|---|---|
| false-positive rate (attenders flagged) | {_p(a.groups["age band"].loc["18-24", "fpr"])} | {_p(a.groups["age band"].loc["55-64", "fpr"])} | **{100 * g["fpr_gap"]:+.1f} pts** |
| recall (no-shows caught) | {_p(a.groups["age band"].loc["18-24", "recall"])} | {_p(a.groups["age band"].loc["55-64", "recall"])} | {100 * g["recall_gap"]:+.1f} pts |
| flagged | {_p(a.groups["age band"].loc["18-24", "flag_rate"])} | {_p(a.groups["age band"].loc["55-64", "flag_rate"])} | {g["flag_rate_ratio"]:.1f}× |

**Cause.** Age is a real (planted) driver: 18–24-year-olds miss far more often. The model is right *on
average* for each group (compare "no-show rate" and "mean prediction" in §3), yet a young patient who would
have attended is {g["fpr_gap"] * 100:.0f} points more likely to be flagged than an older one.

Test set, reporting only: false-positive rate 18-24 {_p(a.test_age.loc["18-24", "fpr"])} vs 55-64 {_p(a.test_age.loc["55-64", "fpr"])}.

**Mitigation options considered:**

| option | effect (validation) | decision |
|---|---|---|
| (a) remove age from the model | PR-AUC {w["pr_auc_with"]:.3f} → {w["pr_auc_without"]:.3f}; false-positive gap {100 * g["fpr_gap"]:+.1f} → {100 * gw["fpr_gap"]:+.1f} pts | Not applied now (test set already used). A candidate for the next model version, with its own validation and test. |
| (b) a different threshold per age group | could equalise false-positive rates | **Rejected**: it deliberately treats people differently by age. |
| (c) supportive use only | the only action is an extra reminder; never refusal, penalty or priority | **Adopted.** A false positive costs one message. |

## 5. Model error vs unavoidable noise

Each outcome is a weighted coin flip, so some errors no model can avoid. With synthetic data we know
the true probability, so we can ask whether a model with *perfect* knowledge (same threshold) would have
made the same mistake.

| error | count | also made by perfect knowledge (unavoidable) | the model's own share |
|---|---|---|---|
| false negatives (missed no-shows) | {s["fn"]:,} | {s["fn_unavoidable"]:,} ({_p(s["fn_unavoidable"] / s["fn"])}) | {_p(1 - s["fn_unavoidable"] / s["fn"])} |
| false positives (flagged attenders) | {s["fp"]:,} | {s["fp_unavoidable"]:,} ({_p(s["fp_unavoidable"] / s["fp"])}) | {_p(1 - s["fp_unavoidable"] / s["fp"])} |

Most errors are the coin flip's, not the model's: even knowing the exact probability, you cannot tell
which of two 20% appointments will be missed.

## 6. Did the model learn the planted formula?

Average change in the predicted probability when only one input changes (all other inputs of each
validation row kept as they are):

| effect | planted direction | model's average change | |
|---|---|---|---|
{direction_rows}

{"Every planted direction was learned." if all_match else "**Finding:** at least one direction does not match the planted formula (marked ❌). Reported as-is."}

Raw logistic-regression weights (inputs are standardised, so sizes are comparable per standard deviation).
Individual weights can look odd because lead time appears three times (raw, log, and inside the
reminder interaction); the table above is the reliable view.

| feature | weight |
|---|---|
{coef_rows}

## 7. Most confident mistakes (synthetic rows)

Attended, but given the highest probability:

{mistakes(a.confident_fp)}

Missed, but given the lowest probability:

{mistakes(a.confident_fn)}

The first group are textbook high-risk profiles (long lead time, no reminder, poor history) who happened
to attend; the second are low-risk profiles who happened to miss. Their true probabilities say the same:
these are mostly coin-flip outcomes, not patterns the model overlooked.
"""


def main():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(analyse()))
    print(f"written to: {REPORT}")


if __name__ == "__main__":
    main()
