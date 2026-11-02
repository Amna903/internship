"""Week 4 Step 8: PCA picture, neutral cluster descriptions, and why clusters are exploratory.

Run:  python -m ml.cluster_view      (writes ml/reports/cluster_view.md and ml/reports/cluster_view.json)

Uses the clusterings fixed in Step 7 (ml/reports/clusters.json: K-Means at each dataset's chosen k):
  - Positive-control data: the 2D PCA picture and the cluster descriptions shown in the dashboard and API,
    always labelled as control data with planted habits, not real patients.
  - Real synthetic patients: no structure was found, but K-Means still returns k groups. They are
    described too, under a heading that says they are misleading and not supported by the baseline, as the
    concrete example of what a false cluster looks like.
Descriptions are built from the numbers, in engagement terms only; a test bans health and personal words.
"""

import json

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from . import cluster, cluster_control, cluster_features, config
from .data import generate

REPORT = config.ML_DIR / "reports" / "cluster_view.md"
RESULT = config.ML_DIR / "reports" / "cluster_view.json"

DISCLAIMER = (
    "Exploratory clustering of synthetic, fictional engagement data. Clusters describe booking "
    "patterns, not categories of people, and are never a medical or personal assessment."
)
CONTROL_LABEL = "Positive-control data with planted habits (fictional), not real patients"
MENTION_SD = 0.3  # a feature is mentioned when the cluster's mean differs from everyone's by this many SDs

PHRASES = {  # (higher than average, lower than average)
    "mean_lead_time": ("books further ahead", "books closer to the date"),
    "telehealth_share": ("more telehealth visits", "fewer telehealth visits"),
    "phone_share": ("books by phone more often", "books by phone less often"),
    "app_share": ("books in the app more often", "books in the app less often"),
    "mean_hour": ("later appointment times", "earlier appointment times"),
    "appointments": ("more appointments in the data", "fewer appointments in the data"),
}


def kmeans_at_chosen_k(table: pd.DataFrame, k: int) -> tuple[np.ndarray, np.ndarray]:
    X = cluster_features.scaled(table)[0]
    return X, cluster.kmeans_labels(X, k)[0]


def describe(table: pd.DataFrame, labels: np.ndarray) -> list[dict]:
    """Per cluster: size, mean of each feature, and a neutral sentence naming the features that set it apart
    (by at least MENTION_SD standard deviations), strongest first."""
    overall, spread = table.mean(), table.std(ddof=0)
    out = []
    for c in sorted(np.unique(labels)):
        rows = table[labels == c]
        means = rows.mean()
        z = ((means - overall) / spread).sort_values(key=abs, ascending=False)
        parts = [PHRASES[f][0 if z[f] > 0 else 1] for f in z.index if abs(z[f]) >= MENTION_SD]
        out.append(
            {
                "cluster": int(c),
                "size": int(len(rows)),
                "share": float(len(rows) / len(table)),
                "profile": {f: float(means[f]) for f in table.columns},
                "description": ("; ".join(parts[:3]) + ".").capitalize()
                if parts
                else "Close to average on every feature.",
            }
        )
    return out


def pca_points(X: np.ndarray) -> tuple[np.ndarray, list[float]]:
    pca = PCA(n_components=2, random_state=config.SEED).fit(X)
    return pca.transform(X), [float(v) for v in pca.explained_variance_ratio_]


def build(df: pd.DataFrame | None = None) -> dict:
    df = generate() if df is None else df
    fixed = cluster.load_result()

    appointments, planted = cluster_control.generate_control()
    control_table = cluster_features.patient_table(appointments)
    cX, c_labels = kmeans_at_chosen_k(control_table, fixed["control"]["chosen_k"]["k-means"])
    c_points, c_variance = pca_points(cX)
    truth = planted.loc[control_table.index].to_numpy()
    control_clusters = describe(control_table, c_labels)
    for item in control_clusters:
        habits = pd.Series(truth[c_labels == item["cluster"]]).value_counts(normalize=True)
        item["most_common_planted_habit"] = {"habit": str(habits.index[0]), "share": float(habits.iloc[0])}

    real_table = cluster_features.patient_table(df)
    rX, r_labels = kmeans_at_chosen_k(real_table, fixed["real"]["chosen_k"]["k-means"])
    _, r_variance = pca_points(rX)
    kmeans_real = fixed["real"]["methods"]["k-means"]

    return {
        "disclaimer": DISCLAIMER,
        "control": {
            "label": CONTROL_LABEL,
            "patients": len(control_table),
            "seed": cluster_control.CONTROL_SEED,
            "k": fixed["control"]["chosen_k"]["k-means"],
            "pca_variance": c_variance,
            "ari": fixed["control"]["methods"]["k-means"]["ari_at_chosen_k"],
            "recovery": cluster.recovery_word(
                max(fixed["control"]["methods"][m]["ari_at_chosen_k"] for m in cluster.METHODS)
            ),
            "clusters": control_clusters,
            "points": [
                {"x": round(float(x), 3), "y": round(float(y), 3), "cluster": int(c), "planted_habit": str(h)}
                for (x, y), c, h in zip(c_points, c_labels, truth)
            ],
        },
        "real": {
            "patients": len(real_table),
            "k": fixed["real"]["chosen_k"]["k-means"],
            "pca_variance": r_variance,
            "structure_found": {m: fixed["real"]["methods"][m]["structure_found"] for m in cluster.METHODS},
            "silhouette": kmeans_real["silhouette"],
            "baseline_bar": kmeans_real["baseline_bar"],
            "appointments_share_of_split": kmeans_real["false_patterns"]["variance_explained"]["appointments"],
            "misleading_clusters": describe(real_table, r_labels),
        },
    }


def to_json(view: dict) -> str:
    return json.dumps(view, indent=2) + "\n"


# ---------------------------------------------------------------- report


def _cluster_rows(clusters: list[dict], with_habit: bool) -> str:
    rows = []
    for c in clusters:
        habit = (
            f" | {c['most_common_planted_habit']['habit']} ({100 * c['most_common_planted_habit']['share']:.0f}%)"
            if with_habit
            else ""
        )
        rows.append(f"| {c['cluster'] + 1} | {c['size']:,} ({100 * c['share']:.0f}%) | {c['description']}{habit} |")
    return "\n".join(rows)


def build_report(view: dict) -> str:
    c, r = view["control"], view["real"]
    c_kept, r_kept = sum(c["pca_variance"]), sum(r["pca_variance"])
    none_found = not any(r["structure_found"].values())

    return f"""# Cluster picture and descriptions

> {view["disclaimer"]} Generated by `python -m ml.cluster_view`; do not edit by hand. Clusterings come
> from Step 7 ([clusters.md](clusters.md)): K-Means at each dataset's chosen k.

## 1. PCA: a 2D picture

PCA turns the six scaled features into two axes that keep as much of their spread as possible. The
dashboard draws the **positive-control data**, labelled "{c["label"]}".

| data | variance kept by 2 axes |
|---|---|
| positive control | {100 * c_kept:.0f}% ({100 * c["pca_variance"][0]:.0f}% + {100 * c["pca_variance"][1]:.0f}%) |
| real synthetic patients | {100 * r_kept:.0f}% ({100 * r["pca_variance"][0]:.0f}% + {100 * r["pca_variance"][1]:.0f}%) |

A 2D picture keeps only part of the spread, so groups can overlap on screen while being apart in six
dimensions, and the reverse. {"For the real data the two axes keep under half the spread: there is no dominant direction, as expected when features are independent." if r_kept < 0.5 else ""}
The picture is for orientation; the cluster quality numbers in [clusters.md](clusters.md) are the evidence.

## 2. Positive-control clusters (planted habits, fictional)

K-Means with k = {c["k"]} (the silhouette rule's choice), {c["patients"]:,} fictional patients. The planted habits were
{c["recovery"]} (ARI {c["ari"]:.3f} for K-Means). Each description names up to three features where the cluster
differs from everyone by at least {MENTION_SD} standard deviations.

| cluster | size | description | most common planted habit |
|---|---|---|---|
{_cluster_rows(c["clusters"], with_habit=True)}

## 3. Clusters K-Means formed anyway on the real data: misleading, not supported by the baseline

{"No structure was found on the real synthetic patients" if none_found else "Structure was reported on the real data"}: K-Means' silhouette ({r["silhouette"]:.3f}) does not beat
the no-habit baseline ({r["baseline_bar"]:.3f}). K-Means still returns k = {r["k"]} groups, because it always returns the
number it is asked for. Here they are, described the same way, as an example of what a false cluster looks
like. {100 * r["appointments_share_of_split"]:.0f}% of the split's variance comes from `appointments`, which differs between patients by chance.

| cluster | size | description |
|---|---|---|
{_cluster_rows(r["misleading_clusters"], with_habit=False)}

## 4. Meaningful versus misleading clusters

- **Misleading:** the real-data groups above. They look tidy and can be described in plain words, yet they
  are no better than data built with no habits at all. They mostly sort patients by how many appointments
  they happen to have.
- **Meaningful, with limits:** the control clusters line up with planted habits, but only partly. Patients
  planted as "mixed" sit between the other habits and can land in any cluster; without them, recovery is
  nearly complete ([clusters.md](clusters.md), diagnostic). Real people are more like the mixed group than
  like neat categories.

## 5. Why clusters are exploratory, not categories of people

- K-Means always returns the number of groups it is asked for, whether or not groups exist; only a
  comparison with a no-structure baseline can tell the difference.
- A cluster summarises averages. Many people in a cluster don't match its description.
- Clusters say how booking patterns differ, never why. They carry no information about health, needs or
  worth, and are never used for decisions about a person.
- A 2D picture can hide or invent separation (section 1).
"""


def main():
    view = build()
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(to_json(view))
    REPORT.write_text(build_report(view))
    print(f"written to: {RESULT}\nwritten to: {REPORT}")


if __name__ == "__main__":
    main()
