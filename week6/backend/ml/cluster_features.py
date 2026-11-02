"""Week 4 Step 6: one row per patient of non-sensitive engagement features, and the scaling choice.

Run:  python -m ml.cluster_features      (writes ml/reports/cluster_features.md)

What is clustered, and why:
  - Patients, not appointments: a pattern of engagement belongs to a person; one appointment has none.
  - Only engagement features, and nothing that is sensitive, locates a person, or is the outcome. The
    excluded columns and the reason for each are in EXCLUDED; a test enforces it.
  - No outcome is an input. The no-show rate may be compared with clusters afterwards, as a description
    only, so clusters can't simply reconstruct the target.

How the generator made these columns (ml/data.py): lead time, hour, visit type and booking channel are
drawn independently for EVERY appointment, with the same probabilities for every patient. There are no
planted patient habits, so differences between patients are chance from about four appointments each.
Weak or no cluster structure is expected, and Step 7 reports what it finds instead of forcing structure.
"""

import numpy as np
import pandas as pd
from sklearn.preprocessing import RobustScaler, StandardScaler

from . import config
from .data import generate

REPORT = config.ML_DIR / "reports" / "cluster_features.md"

FEATURES = {
    "mean_lead_time": "average days between booking and appointment",
    "telehealth_share": "share of appointments by telehealth",
    "phone_share": "share booked by phone",
    "app_share": "share booked in the app",
    "mean_hour": "average appointment hour",
    "appointments": "number of appointments in the data",
}

EXCLUDED = {
    "age_band": "sensitive attribute",
    "distance_km": "location data",
    "prior_appointments": "history count tied to the outcome history",
    "prior_no_shows": "outcome history",
    "no_show": "the outcome",
    config.ORACLE: "the generator's true outcome probability",
    "reminder_sent": "reflects what the clinic does, not how the patient engages",
    "web_share": "web = 1 - phone - app; keeping all three would count booking channel twice in distances",
    "appointment_weekday": "seven-way category; adds dimensions without an engagement meaning",
    "appointment_id": "identifier",
}

# Scaling rule, fixed before any clustering: K-Means compares distances, so unscaled days (0-90) would swamp
# shares (0-1). StandardScaler (mean/sd) by default; RobustScaler (median/IQR) if any feature has extreme
# outliers (max |z| above OUTLIER_Z after standard scaling). Outliers stay far away under either scaler;
# what RobustScaler prevents is a few extreme patients SETTING the scale: they inflate the sd, which squeezes
# the typical patients together. RobustScaler needs every IQR above zero (it can't divide by a zero spread).
OUTLIER_Z = 5.0


def patient_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per patient, indexed by patient_id, columns in FEATURES order."""
    g = df.groupby("patient_id")
    return pd.DataFrame(
        {
            "mean_lead_time": g["lead_time_days"].mean(),
            "telehealth_share": g["visit_type"].agg(lambda s: (s == "telehealth").mean()),
            "phone_share": g["booking_channel"].agg(lambda s: (s == "phone").mean()),
            "app_share": g["booking_channel"].agg(lambda s: (s == "app").mean()),
            "mean_hour": g["appointment_hour"].mean(),
            "appointments": g.size().astype(float),
        }
    )[list(FEATURES)]


def scaling_facts(table: pd.DataFrame) -> dict:
    z = (table - table.mean()) / table.std(ddof=0)
    q1, q3 = table.quantile(0.25), table.quantile(0.75)
    return {
        f: {"max_abs_z": float(z[f].abs().max()), "iqr": float(q3[f] - q1[f]), "skew": float(table[f].skew())}
        for f in table.columns
    }


def choose_scaler(facts: dict) -> tuple[str, str]:
    """Apply the rule written above. Returns (scaler name, reason)."""
    outliers = [f for f, x in facts.items() if x["max_abs_z"] > OUTLIER_Z]
    zero_spread = [f for f, x in facts.items() if x["iqr"] == 0]
    if not outliers:
        return "standard", f"no feature has max |z| above {OUTLIER_Z}"
    if zero_spread:
        return "standard", (
            f"{', '.join(outliers)} has outliers, but {', '.join(zero_spread)} has zero IQR, which "
            "RobustScaler can't divide by"
        )
    return "robust", (
        f"{', '.join(f'`{f}`' for f in outliers)} has extreme outliers (max |z| above {OUTLIER_Z}), and "
        "every feature has a non-zero IQR"
    )


def scaler_for(name: str):
    return RobustScaler() if name == "robust" else StandardScaler()


def scaled(table: pd.DataFrame) -> tuple[np.ndarray, str, str]:
    """The scaled feature matrix, the scaler chosen by the rule, and the reason. There is no train/test split
    here: clustering describes this whole fictional population and makes no predictions on new rows, so
    fitting the scaler on all patients leaks nothing."""
    name, reason = choose_scaler(scaling_facts(table))
    return scaler_for(name).fit_transform(table), name, reason


# ---------------------------------------------------------------- report


def build_report(df: pd.DataFrame) -> str:
    table = patient_table(df)
    facts = scaling_facts(table)
    name, reason = choose_scaler(facts)
    corr = table.corr()
    pairs = [(a, b, corr.loc[a, b]) for i, a in enumerate(table.columns) for b in table.columns[i + 1 :]]
    strongest = max(pairs, key=lambda p: abs(p[2]))
    others = max((p for p in pairs if p[:2] != strongest[:2]), key=lambda p: abs(p[2]))
    feature_rows = "\n".join(
        f"| `{f}` | {d} | {table[f].median():.2f} | {facts[f]['iqr']:.2f} | {facts[f]['skew']:+.2f} | {facts[f]['max_abs_z']:.1f} |"
        for f, d in FEATURES.items()
    )
    excluded_rows = "\n".join(f"| `{c}` | {why} |" for c, why in EXCLUDED.items())
    single = int((table["appointments"] == 1).sum())
    corr_rows = "\n".join(
        "| `" + a + "` | " + " | ".join(f"{corr.loc[a, b]:+.2f}" for b in table.columns) + " |" for a in table.columns
    )

    return f"""# Clustering features: one row per patient

> Synthetic, educational data. Generated by `python -m ml.cluster_features`; do not edit by hand. Clusters
> built on these features are exploratory descriptions of engagement patterns, not categories of people,
> and never a medical assessment.

{len(table):,} fictional patients, built from their {len(df):,} appointments. No outcome is an input.

## 1. Features

| feature | meaning | median | IQR | skew | max \\|z\\| |
|---|---|---|---|---|---|
{feature_rows}

## 2. Left out, and why

| column | reason |
|---|---|
{excluded_rows}

## 3. How the generator made these columns

Lead time, hour, visit type and booking channel are drawn **independently for every appointment, with
the same probabilities for every patient** (`ml/data.py`). There are no planted patient habits: two
patients differ only by chance, from about four appointments each. **Weak or no cluster structure is
expected.** Step 7 compares the clusters with a shuffled baseline and reports what it finds, rather than
tuning until clusters appear.

The correlations agree:

| | {" | ".join(f"`{c}`" for c in table.columns)} |
|---|{"---|" * len(table.columns)}
{corr_rows}

The strongest pair is `{strongest[0]}` / `{strongest[1]}` ({strongest[2]:+.2f}): {
        "two shares of the same booking-channel draws, which compete for the same appointments, so a negative link is built in, not a habit."
        if {strongest[0], strongest[1]} == {"phone_share", "app_share"}
        else "see the table."
    }
Every other pair is within {abs(others[2]):.2f} of zero.

## 4. Scaling

K-Means compares distances, so without scaling the lead time (in days, 0–90) would swamp the shares
(0–1). The rule, fixed before clustering: StandardScaler by default; RobustScaler (median and IQR) if any
feature has extreme outliers (max |z| above {OUTLIER_Z}), provided every feature has a non-zero IQR.
Outliers stay far away under either scaler; what RobustScaler prevents is a few extreme patients setting
the scale (they inflate the standard deviation, which squeezes the typical patients together).

**Chosen: {"RobustScaler" if name == "robust" else "StandardScaler"}**, because {reason}.

There is no train/test split here. Clustering describes this whole fictional population and makes no
predictions on new rows, so fitting the scaler on all patients leaks nothing.

## 5. Patients with one appointment

{single:,} patients ({100 * single / len(table):.1f}%) have a single appointment, so each of their shares is
exactly 0 or 1. They are kept: removing them after seeing clusters would be choosing the data to fit the
result. Step 7 checks whether any cluster is mostly made of them, which would mean it groups appointment
counts, not engagement.
"""


def main():
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(generate()))
    print(f"written to: {REPORT}")


if __name__ == "__main__":
    main()
