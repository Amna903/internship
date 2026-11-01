"""Week 4 Step 7: two clustering methods on two datasets, judged by rules fixed before they ran.

Run:  python -m ml.cluster      (writes ml/reports/clusters.md and ml/reports/clusters.json)

  1. The real synthetic patients (ml/cluster_features.py). They have no planted habits, so the honest
     question is whether clustering finds anything beyond chance. It is compared with a baseline that
     reshuffles APPOINTMENTS between patients, keeping each patient's number of appointments: that keeps
     every link that comes from how the features are calculated (one-appointment patients have shares of
     0 or 1; phone and app shares come from the same bookings) and removes only habits.
  2. The positive control (ml/cluster_control.py), with four planted habits: do the methods recover them?

Rules, fixed before running:
  - Methods: K-Means and agglomerative clustering (Ward), k = 2..8.
  - k: the best silhouette wins; within K_TIE of the best, fewer clusters win.
  - Verdict on the real data: "structure found" only if its silhouette (at its chosen k) beats the 95th
    percentile of the same procedure on the reshuffled baselines. Otherwise "no structure found".
  - If structure is found, three false-pattern checks run before anything is called a habit: is a
    cluster mostly one-appointment patients, is the split mainly by appointment count, is it mainly the
    phone/app split.
  - Control: adjusted Rand index (ARI) against the planted habits; K-Means stability over 10 seeds.
"""

import json

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score

from . import cluster_control, cluster_features, config
from .data import generate

REPORT = config.ML_DIR / "reports" / "clusters.md"
RESULT = config.ML_DIR / "reports" / "clusters.json"

K_RANGE = range(2, 9)
K_TIE = 0.01
BASELINE_RUNS = 20
BASELINE_PERCENTILE = 95
STABILITY_SEEDS = 10
SINGLES_MAJORITY = 0.5  # a cluster that is more than half one-appointment patients groups counts, not habits
METHODS = ("k-means", "agglomerative (Ward)")

# Words for recovery, by the best adjusted Rand index of the two methods. ARI is 0 for chance agreement and
# 1 for a perfect match; there is no universal scale, so these are rough guides: 0.8 or more means the
# groups are essentially reproduced, 0.5 to 0.8 that most assignments agree, 0.2 to 0.5 that there is some
# agreement beyond chance. SET AFTER SEEING the first control result (best ARI 0.52); recorded as such in
# the report and docs/REQUIREMENTS.md.
RECOVERY_WORDS = [(0.8, "recovered well"), (0.5, "partially recovered"), (0.2, "weakly recovered"),
                  (float("-inf"), "not recovered")]


def recovery_word(ari: float) -> str:
    return next(word for threshold, word in RECOVERY_WORDS if ari >= threshold)


BORDERLINE_MARGIN = 0.05  # an ARI this close to a word threshold makes its label borderline


def borderline_note(ari: float) -> str:
    """Say so when the ARI sits close to a threshold, because the thresholds were set after seeing it."""
    for threshold, _ in RECOVERY_WORDS[:-1]:
        if abs(ari - threshold) < BORDERLINE_MARGIN:
            side = "just above" if ari >= threshold else "just below"
            return (f" {ari:.2f} sits {side} the {threshold:g} threshold, so the '{recovery_word(ari)}' label is "
                    "borderline.")
    return ""


def kmeans_labels(X: np.ndarray, k: int, seed: int = config.SEED) -> tuple[np.ndarray, float]:
    model = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(X)
    return model.labels_, float(model.inertia_)


def scan(X: np.ndarray) -> dict:
    """Silhouette for every k and both methods (Ward's tree is built once and cut at each k), and K-Means
    inertia for the elbow."""
    tree = linkage(X, method="ward")
    out = {m: {} for m in METHODS}
    inertia = {}
    for k in K_RANGE:
        labels, inertia[k] = kmeans_labels(X, k)
        out["k-means"][k] = float(silhouette_score(X, labels))
        out["agglomerative (Ward)"][k] = float(silhouette_score(X, fcluster(tree, k, criterion="maxclust")))
    return {"silhouette": out, "inertia": inertia, "tree": tree}


def choose_k(silhouettes: dict) -> int:
    best = max(silhouettes.values())
    return min(k for k, s in silhouettes.items() if s >= best - K_TIE)


def labels_for(X: np.ndarray, method: str, k: int, tree=None) -> np.ndarray:
    if method == "k-means":
        return kmeans_labels(X, k)[0]
    return fcluster(linkage(X, method="ward") if tree is None else tree, k, criterion="maxclust") - 1


def reshuffle_appointments(appointments: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """The no-habit baseline: every appointment's attributes are moved to a random slot, but each patient
    keeps exactly as many appointments as before. Lead time and hour distributions, the 0/1 shares of
    one-appointment patients and the phone/app link all survive; only a patient's appointments resembling
    each other (a habit) is removed."""
    attributes = ["lead_time_days", "visit_type", "booking_channel", "appointment_hour"]
    shuffled = appointments.copy()
    shuffled[attributes] = appointments[attributes].iloc[rng.permutation(len(appointments))].to_numpy()
    return shuffled


def best_silhouette(X: np.ndarray) -> dict:
    s = scan(X)["silhouette"]
    return {m: s[m][choose_k(s[m])] for m in METHODS}


def variance_explained(table: pd.DataFrame, labels: np.ndarray) -> dict:
    """Per feature, the share of its (scaled) variance that lies between clusters: what the split is 'about'."""
    X = pd.DataFrame(cluster_features.scaled(table)[0], columns=table.columns, index=table.index)
    out = {}
    for f in X.columns:
        total = float(((X[f] - X[f].mean()) ** 2).sum())
        between = float(sum(len(g) * (g.mean() - X[f].mean()) ** 2 for _, g in X[f].groupby(labels)))
        out[f] = between / total if total else 0.0
    return out


def false_pattern_checks(table: pd.DataFrame, labels: np.ndarray) -> dict:
    singles = (table["appointments"] == 1).to_numpy()
    single_share = {int(c): float(singles[labels == c].mean()) for c in np.unique(labels)}
    explained = variance_explained(table, labels)
    main = max(explained, key=explained.get)
    checks = {
        "mostly one-appointment patients": max(single_share.values()) > SINGLES_MAJORITY,
        "split mainly by appointment count": main == "appointments",
        "split mainly by phone/app share": main in ("phone_share", "app_share"),
    }
    return {"checks": checks, "largest_single_share": max(single_share.values()), "main_feature": main,
            "variance_explained": explained}


def analyse_real(df: pd.DataFrame, runs: int = BASELINE_RUNS) -> dict:
    appointments = df[["patient_id", "lead_time_days", "visit_type", "booking_channel", "appointment_hour"]]
    table = cluster_features.patient_table(df)
    X = cluster_features.scaled(table)[0]
    s = scan(X)
    chosen = {m: choose_k(s["silhouette"][m]) for m in METHODS}
    rng = np.random.default_rng(config.SEED)
    baseline = {m: [] for m in METHODS}
    for _ in range(runs):
        shuffled_table = cluster_features.patient_table(reshuffle_appointments(appointments, rng))
        for m, value in best_silhouette(cluster_features.scaled(shuffled_table)[0]).items():
            baseline[m].append(value)
    out = {"patients": len(table), "silhouette": s["silhouette"], "inertia": s["inertia"], "chosen_k": chosen,
           "baseline": baseline, "methods": {}}
    for m in METHODS:
        real = s["silhouette"][m][chosen[m]]
        bar = float(np.percentile(baseline[m], BASELINE_PERCENTILE))
        labels = labels_for(X, m, chosen[m], s["tree"])
        out["methods"][m] = {"silhouette": real, "baseline_bar": bar, "structure_found": real > bar,
                             "false_patterns": false_pattern_checks(table, labels),
                             "sizes": np.bincount(labels).tolist()}
    return out


def _ari_both(table: pd.DataFrame, truth: np.ndarray, k: int) -> dict:
    X = cluster_features.scaled(table)[0]
    return {m: float(adjusted_rand_score(truth, labels_for(X, m, k))) for m in METHODS}


def control_diagnostics(table: pd.DataFrame, truth: np.ndarray) -> dict:
    """Diagnostics, NOT the result: what limits recovery? ARI at the planted number of groups when (a) the
    `appointments` feature is left out (it is drawn the same way for every habit, so it is pure noise
    here) and (b) the 'mixed' group, planted between the others, is left out."""
    n = len(cluster_control.HABITS)
    keep = truth != "mixed"
    return {
        "all features, all groups": {"k": n, "ari": _ari_both(table, truth, n)},
        "without the appointments feature": {"k": n, "ari": _ari_both(table.drop(columns="appointments"), truth, n)},
        "without the 'mixed' group": {"k": n - 1, "ari": _ari_both(table[keep], truth[keep], n - 1)},
    }


def analyse_control() -> dict:
    appointments, planted = cluster_control.generate_control()
    table = cluster_features.patient_table(appointments)
    truth = planted.loc[table.index].to_numpy()
    X = cluster_features.scaled(table)[0]
    s = scan(X)
    chosen = {m: choose_k(s["silhouette"][m]) for m in METHODS}
    n_planted = len(cluster_control.HABITS)
    out = {"patients": len(table), "planted_groups": n_planted, "silhouette": s["silhouette"], "inertia": s["inertia"],
           "chosen_k": chosen, "methods": {}}
    for m in METHODS:
        at_chosen = labels_for(X, m, chosen[m], s["tree"])
        at_planted = labels_for(X, m, n_planted, s["tree"])
        out["methods"][m] = {"ari_at_chosen_k": float(adjusted_rand_score(truth, at_chosen)),
                             "ari_at_planted_k": float(adjusted_rand_score(truth, at_planted))}
    out["diagnostics"] = control_diagnostics(table, truth)
    runs = [kmeans_labels(X, chosen["k-means"], seed)[0] for seed in range(STABILITY_SEEDS)]
    pairs = [adjusted_rand_score(runs[i], runs[j]) for i in range(len(runs)) for j in range(i + 1, len(runs))]
    out["kmeans_stability"] = {"mean_pairwise_ari": float(np.mean(pairs)), "min_pairwise_ari": float(np.min(pairs))}
    return out


def run(df: pd.DataFrame | None = None, runs: int = BASELINE_RUNS) -> dict:
    df = generate() if df is None else df
    return {"seed": config.SEED, "control_seed": cluster_control.CONTROL_SEED, "k_range": list(K_RANGE),
            "baseline_runs": runs, "real": analyse_real(df, runs), "control": analyse_control()}


# ---------------------------------------------------------------- report

def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    return value


def to_json(result: dict) -> str:
    return json.dumps(_jsonable(result), indent=2) + "\n"


def load_result() -> dict:
    """The committed result, with k back as integers (JSON keys are strings)."""
    result = json.loads(RESULT.read_text())
    for part in ("real", "control"):
        section = result[part]
        section["silhouette"] = {m: {int(k): v for k, v in by_k.items()} for m, by_k in section["silhouette"].items()}
        section["inertia"] = {int(k): v for k, v in section["inertia"].items()}
    return result


def _k_table(section: dict) -> str:
    header = "| k | " + " | ".join(f"silhouette, {m}" for m in METHODS) + " | k-means inertia (elbow) |"
    rows = [f"| {k} | " + " | ".join(f"{section['silhouette'][m][k]:.3f}{' ←' if section['chosen_k'][m] == k else ''}"
                                     for m in METHODS) + f" | {section['inertia'][k]:,.0f} |" for k in K_RANGE]
    return header + "\n|---|" + "---|" * (len(METHODS) + 1) + "\n" + "\n".join(rows)


def _verdict_line(m: str, r: dict) -> str:
    v = r["methods"][m]
    found = "**structure found**" if v["structure_found"] else "**no structure found**"
    return (f"| {m} | {r['chosen_k'][m]} | {v['silhouette']:.3f} | {v['baseline_bar']:.3f} | {found} |")


def _false_pattern_text(m: str, v: dict) -> str:
    fp = v["false_patterns"]
    flagged = [name for name, hit in fp["checks"].items() if hit]
    lead = (f"- **{m}**: the split is mostly about `{fp['main_feature']}` "
            f"({100 * fp['variance_explained'][fp['main_feature']]:.0f}% of its variance lies between clusters); "
            f"largest share of one-appointment patients in a cluster: {100 * fp['largest_single_share']:.0f}%. ")
    if not v["structure_found"]:
        return lead + "Reported for completeness; with no structure found, there is nothing to call a habit."
    if flagged:
        return lead + f"Flagged: {', '.join(flagged)}. **Not a habit**: the clusters follow how the features are calculated."
    return lead + "Passes all three checks: possibly an engagement pattern, still exploratory."


def build_report(result: dict) -> str:
    r, c = result["real"], result["control"]
    verdicts = "\n".join(_verdict_line(m, r) for m in METHODS)
    false_patterns = "\n".join(_false_pattern_text(m, r["methods"][m]) for m in METHODS)
    any_found = any(r["methods"][m]["structure_found"] for m in METHODS)
    recovery = "\n".join(
        f"| {m} | {c['chosen_k'][m]} | {c['methods'][m]['ari_at_chosen_k']:.3f} | {c['methods'][m]['ari_at_planted_k']:.3f} |"
        for m in METHODS)
    stab = c["kmeans_stability"]
    best_ari = max(c["methods"][m]["ari_at_chosen_k"] for m in METHODS)
    word = recovery_word(best_ari)
    d = c["diagnostics"]
    diagnostic_rows = "\n".join(f"| {name} | {v['k']} | " + " | ".join(f"{v['ari'][m]:.3f}" for m in METHODS) + " |"
                                 for name, v in d.items())
    base = max(d["all features, all groups"]["ari"].values())
    no_count = max(d["without the appointments feature"]["ari"].values())
    no_mixed = max(d["without the 'mixed' group"]["ari"].values())
    diagnostic_reading = (
        f"At the planted number of groups, leaving out `appointments` changes the best ARI from {base:.3f} to "
        f"{no_count:.3f}; leaving out the 'mixed' "
        f"group changes it to {no_mixed:.3f}. "
        + ("The noise feature is the larger limit. " if no_count - base > no_mixed - base else
           "The in-between group is the larger limit. ")
        + f"Real data: the K-Means split there is mostly about `appointments` "
        f"({100 * r['methods']['k-means']['false_patterns']['variance_explained']['appointments']:.0f}% of its variance "
        "between clusters). **Lesson: `appointments` both blurs real groups (control) and drives a false split "
        "(real data)**, because it differs between patients by chance and counts as one sixth of every distance.")
    found_k = [m for m in METHODS if c["chosen_k"][m] == c["planted_groups"]]

    return f"""# Clustering: real patients and a positive control

> Synthetic, educational data. Generated by `python -m ml.cluster`; do not edit by hand. Clusters are
> exploratory descriptions of engagement patterns, not categories of people, and never a medical
> assessment.

Rules, fixed before running: K-Means and agglomerative clustering (Ward) for k = {K_RANGE.start}–{K_RANGE.stop - 1}; the
best silhouette chooses k, and within {K_TIE} of the best, fewer clusters win. Features and scaling as in
[cluster_features.md](cluster_features.md).

## 1. Real synthetic patients: is there any structure?

{r['patients']:,} patients. The generator plants no patient habits, so the question is whether clustering
finds anything beyond chance.

{_k_table(r)}

**Baseline.** {result['baseline_runs']} reshuffles (seed {result['seed']}) that move appointments between patients while each
patient keeps their number of appointments. This keeps every link that comes from how the features are
calculated (one-appointment patients still have shares of exactly 0 or 1; phone and app shares still come
from the same bookings) and removes only habits. Each reshuffle goes through the same procedure,
including choosing its own best k.

Verdict rule: structure found only if the real silhouette beats the {BASELINE_PERCENTILE}th percentile of the baseline.

Reproducibility note: Ward's tree can differ between machines when patients have identical feature
values (common with about four appointments each), because exactly tied merges are ordered by
floating-point rounding. Individual baseline runs may therefore differ slightly between machines; the
verdict, the chosen k, the {BASELINE_PERCENTILE}th-percentile bar and the median of the baseline runs are checked strictly.

| method | chosen k | real silhouette | baseline {BASELINE_PERCENTILE}th percentile | verdict |
|---|---|---|---|---|
{verdicts}

{"Clustering finds something beyond the no-habit baseline; the checks below decide whether it is a habit or an artefact." if any_found else
"**No structure found.** The clusters on the real data are no better than on data where patients have no habits by construction. That matches how the data was generated: any grouping here would be splitting noise."}

False-pattern checks (decisive only when structure is found):

{false_patterns}

## 2. Positive control: are planted habits recovered?

{c['patients']:,} fictional patients from a separate generator (`ml/cluster_control.py`, seed {result['control_seed']}) with
{c['planted_groups']} planted engagement habits, planted with overlap. The habit labels are used only to score recovery.

{_k_table(c)}

Adjusted Rand index against the planted habits (1 = perfect recovery, 0 = no better than chance):

| method | chosen k | ARI at chosen k | ARI at the planted k ({c['planted_groups']}) |
|---|---|---|---|
{recovery}

**Result: the planted habits were {word} (best ARI {best_ari:.3f}).** {("The silhouette rule found the planted number of groups with " + ", ".join(found_k) + ".") if found_k else
f"The silhouette rule did not land on the planted {c['planted_groups']} groups with either method; reported as-is."}
K-Means stability over {STABILITY_SEEDS} seeds: mean pairwise ARI {stab['mean_pairwise_ari']:.3f} (lowest {stab['min_pairwise_ari']:.3f}).

Words used for ARI, as rough guides (there is no universal scale): {"; ".join(f"{t:g} or more: {w}" for t, w in RECOVERY_WORDS[:-1])};
below {RECOVERY_WORDS[-2][0]:g}: {RECOVERY_WORDS[-1][1]}. **These thresholds were set after seeing this result.**{borderline_note(best_ari)}

### Diagnostic (not the result): what limits recovery?

ARI at the planted number of groups (so the first row differs from the main result, which is at the k
the silhouette rule chose), with one suspected cause removed at a time. The control and the main result
above are unchanged.

| setting | k | {" | ".join(f"ARI, {m}" for m in METHODS)} |
|---|---|{"---|" * len(METHODS)}
{diagnostic_rows}

{diagnostic_reading}

## 3. What the two results show together

With the same features, scaling and methods, the planted habits were {word} on the control data
(best ARI {best_ari:.3f}), and the real data showed {"something that the checks above examine" if any_found else "nothing beyond chance"}. So the methods
can pick up planted structure, imperfectly, and the real "no structure" result is not just a broken
pipeline. Clusters
are always exploratory: K-Means returns k groups for any data, which is why the baseline and the control
matter more than how tidy the groups look.
"""


def main():
    result = run()
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(to_json(result))
    REPORT.write_text(build_report(result))
    print(f"written to: {RESULT}\nwritten to: {REPORT}")


if __name__ == "__main__":
    main()
