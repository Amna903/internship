"""Reproducible training run: data -> split -> candidates -> pick on validation -> test once -> artifact.

    python -m ml.train            # writes ml/artifacts/ and ml/reports/metrics.md

Same code + same pinned libraries + same seed => same data hash, same metrics, same predictions
(checked by tests/test_ml_training.py).
"""

import argparse
import json
import platform
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score, brier_score_loss, confusion_matrix, f1_score, log_loss,
    precision_recall_curve, precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline

from . import config, data
from .features import EXCLUDED_COLUMNS, INPUT_BOOLEAN, INPUT_CATEGORICAL, INPUT_COLUMNS, INPUT_NUMERIC, build_preprocessor


def candidates(seed: int) -> dict[str, Pipeline]:
    def logistic(engineered: bool):
        return Pipeline([
            ("prep", build_preprocessor(scale=True, engineered=engineered)),
            ("model", LogisticRegression(max_iter=2000, C=1.0)),
        ])

    def hgb(**params):
        return Pipeline([
            ("prep", build_preprocessor(scale=False, engineered=True)),
            ("model", HistGradientBoostingClassifier(early_stopping=False, random_state=seed, **params)),
        ])

    return {
        # Floor: predicts the training no-show rate for everyone. Anything useful must beat it.
        "majority_prior": Pipeline([("prep", build_preprocessor(scale=False)), ("model", DummyClassifier(strategy="prior"))]),
        # Baseline: linear model on the raw inputs only.
        "logistic_raw": logistic(engineered=False),
        # Improved candidates: EDA-driven features, then a linear and a tree model on them.
        "logistic_engineered": logistic(engineered=True),
        "hist_gradient_boosting": hgb(
            learning_rate=0.03, max_iter=400, max_leaf_nodes=8, min_samples_leaf=80, l2_regularization=1.0
        ),
    }


def split(df: pd.DataFrame, seed: int):
    """Patient-grouped split: every appointment of a patient lands in exactly one split, so the test set
    measures performance on *new* patients rather than people the model has already seen."""
    groups = df["patient_ref"]
    outer = GroupShuffleSplit(n_splits=1, test_size=config.TEST_SIZE, random_state=seed)
    trainval_idx, test_idx = next(outer.split(df, groups=groups))
    trainval = df.iloc[trainval_idx]
    inner = GroupShuffleSplit(n_splits=1, test_size=config.VAL_SIZE / (1 - config.TEST_SIZE), random_state=seed)
    train_idx, val_idx = next(inner.split(trainval, groups=trainval["patient_ref"]))
    return trainval.iloc[train_idx], trainval.iloc[val_idx], df.iloc[test_idx]


def xy(df: pd.DataFrame):
    return df[INPUT_COLUMNS], df[config.TARGET].to_numpy()


def ranking_metrics(y, p) -> dict:
    return {
        "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4),
        "brier": round(float(brier_score_loss(y, p)), 4),
        "log_loss": round(float(log_loss(y, p)), 4),
    }


def threshold_metrics(y, p, threshold: float) -> dict:
    pred = (p >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    return {
        "threshold": round(threshold, 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y, pred)), 4),
        "f1": round(float(f1_score(y, pred)), 4),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def best_f1_threshold(y, p) -> float:
    precision, recall, thresholds = precision_recall_curve(y, p)
    f1 = 2 * precision * recall / np.clip(precision + recall, 1e-12, None)
    return float(thresholds[int(np.argmax(f1[:-1]))])


def error_analysis(test: pd.DataFrame, p: np.ndarray, threshold: float) -> dict:
    frame = test.assign(p=p, pred=(p >= threshold).astype(int))
    out = {}
    for column in ["age_band", "visit_type", "reminder_sent"]:
        rows = []
        for value, g in frame.groupby(column, sort=True):
            positives, negatives = g[g.no_show == 1], g[g.no_show == 0]
            rows.append({
                "value": str(value),
                "n": int(len(g)),
                "observed_rate": round(float(g.no_show.mean()), 3),
                "mean_predicted": round(float(g.p.mean()), 3),
                "recall": round(float(positives.pred.mean()), 3) if len(positives) else None,
                "false_positive_rate": round(float(negatives.pred.mean()), 3) if len(negatives) else None,
            })
        out[column] = rows
    deciles = pd.qcut(frame.p, 10, labels=False, duplicates="drop")
    out["calibration_deciles"] = [
        {"decile": int(d), "mean_predicted": round(float(g.p.mean()), 3), "observed_rate": round(float(g.no_show.mean()), 3), "n": int(len(g))}
        for d, g in frame.groupby(deciles)
    ]
    missed = frame[(frame.no_show == 1) & (frame.pred == 0)]
    out["missed_no_shows_profile"] = {
        "count": int(len(missed)),
        "share_with_reminder": round(float(missed.reminder_sent.mean()), 3),
        "median_lead_time_days": float(missed.lead_time_days.median()),
        "share_zero_prior_no_shows": round(float((missed.prior_no_shows == 0).mean()), 3),
    }
    return out


def run(out_dir: Path = config.ARTIFACT_DIR, report_dir: Path = config.REPORT_DIR,
        n_rows: int = config.N_ROWS, seed: int = config.SEED, data_path: Path = config.DATA_PATH) -> dict:
    df = data.generate(n_rows=n_rows, seed=seed)
    data_sha = data.write(df, data_path)
    train, val, test = split(df, seed)
    assert not set(train.patient_ref) & set(test.patient_ref), "patient leaked across splits"
    X_train, y_train = xy(train)
    X_val, y_val = xy(val)
    X_test, y_test = xy(test)

    validation = {}
    fitted = {}
    for name, pipe in candidates(seed).items():
        pipe.fit(X_train, y_train)
        fitted[name] = pipe
        validation[name] = ranking_metrics(y_val, pipe.predict_proba(X_val)[:, 1])

    learned = [n for n in validation if n != "majority_prior"]
    selected = max(learned, key=lambda n: (validation[n]["pr_auc"], validation[n]["roc_auc"]))
    model = fitted[selected]
    threshold = best_f1_threshold(y_val, model.predict_proba(X_val)[:, 1])

    # The test set is touched once, after every choice (model, thresholds) was made on validation.
    # Every candidate is reported so the comparison is visible; only `selected` is shipped.
    test_metrics = {}
    for name, pipe in fitted.items():
        p = pipe.predict_proba(X_test)[:, 1]
        test_metrics[name] = ranking_metrics(y_test, p)
        if name != "majority_prior":
            t = threshold if name == selected else best_f1_threshold(y_val, pipe.predict_proba(X_val)[:, 1])
            test_metrics[name].update(threshold_metrics(y_test, p, t))
    p_test = model.predict_proba(X_test)[:, 1]
    # Best possible score on this test set: rank by the generator's true probability.
    test_metrics["oracle_ceiling"] = ranking_metrics(y_test, test[data.TRUTH_COLUMN].to_numpy())

    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / f"{config.MODEL_NAME}-{config.MODEL_VERSION}.joblib"
    joblib.dump(model, artifact)

    metadata = {
        "model_name": config.MODEL_NAME,
        "model_version": config.MODEL_VERSION,
        "selected_model": selected,
        "task": "Probability that a synthetic appointment is missed (no-show). Educational, non-diagnostic.",
        "artifact_file": artifact.name,
        "artifact_sha256": data.file_sha256(artifact),
        "decision_threshold": round(threshold, 4),
        "train_no_show_rate": round(float(y_train.mean()), 4),
        "seed": seed,
        "data": {
            "file": data_path.name,
            "sha256": data_sha,
            "rows": int(len(df)),
            "split_rows": {"train": int(len(train)), "validation": int(len(val)), "test": int(len(test))},
            "split_no_show_rate": {
                "train": round(float(y_train.mean()), 4), "validation": round(float(y_val.mean()), 4),
                "test": round(float(y_test.mean()), 4),
            },
            "split": "GroupShuffleSplit by patient_ref (60/20/20)",
        },
        "features": {
            "numeric": INPUT_NUMERIC, "categorical": INPUT_CATEGORICAL, "boolean": INPUT_BOOLEAN,
            "excluded": EXCLUDED_COLUMNS,
        },
        "validation_metrics": validation,
        "test_metrics": test_metrics,
        "error_analysis": error_analysis(test, p_test, threshold),
        "environment": {
            "python": platform.python_version(), "scikit_learn": sklearn.__version__,
            "numpy": np.__version__, "pandas": pd.__version__, "joblib": joblib.__version__,
        },
    }
    (out_dir / f"{config.MODEL_NAME}-{config.MODEL_VERSION}.json").write_text(json.dumps(metadata, indent=2) + "\n")
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "metrics.md").write_text(render_report(metadata))
    return metadata


def render_report(m: dict) -> str:
    sel = m["selected_model"]
    lines = [
        f"# Model report: {m['model_name']} {m['model_version']}",
        "",
        "Generated by `python -m ml.train`. Synthetic data, educational only, not clinically validated.",
        "",
        f"Data: {m['data']['rows']} rows, sha256 `{m['data']['sha256'][:16]}…`, split {m['data']['split']}: "
        + ", ".join(f"{k} {v} rows ({m['data']['split_no_show_rate'][k]:.1%} no-show)" for k, v in m["data"]["split_rows"].items()),
        "",
        "## Validation (all candidates; selection by PR-AUC)",
        "",
        "| Model | ROC-AUC | PR-AUC | Brier | Log loss |",
        "|---|---|---|---|---|",
    ]
    for name, v in m["validation_metrics"].items():
        mark = " **(selected)**" if name == sel else ""
        lines.append(f"| {name}{mark} | {v['roc_auc']} | {v['pr_auc']} | {v['brier']} | {v['log_loss']} |")
    lines += [
        "",
        f"## Test (touched once; threshold {m['decision_threshold']} chosen on validation by best F1)",
        "",
        "| Model | ROC-AUC | PR-AUC | Brier | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|---|",
    ]
    # oracle_ceiling = ranking by the generator's true probability: the best any model could do here.
    for name, t in m["test_metrics"].items():
        lines.append(
            f"| {name}{' **(selected)**' if name == sel else ''} | {t['roc_auc']} | {t['pr_auc']} | {t['brier']} | "
            f"{t.get('precision', '–')} | {t.get('recall', '–')} | {t.get('f1', '–')} |"
        )
    cm = m["test_metrics"][sel]["confusion_matrix"]
    lines += [
        "",
        f"Confusion matrix ({sel}, test): TN {cm['tn']} · FP {cm['fp']} · FN {cm['fn']} · TP {cm['tp']}",
        "",
        "## Error analysis (selected model, test set)",
    ]
    ea = m["error_analysis"]
    for column in ["age_band", "visit_type", "reminder_sent"]:
        lines += ["", f"**By {column}**", "", "| Value | n | Observed | Mean predicted | Recall | FPR |", "|---|---|---|---|---|---|"]
        for r in ea[column]:
            lines.append(f"| {r['value']} | {r['n']} | {r['observed_rate']} | {r['mean_predicted']} | {r['recall']} | {r['false_positive_rate']} |")
    lines += ["", "**Calibration (deciles of predicted probability)**", "", "| Decile | n | Mean predicted | Observed |", "|---|---|---|---|"]
    for r in ea["calibration_deciles"]:
        lines.append(f"| {r['decile']} | {r['n']} | {r['mean_predicted']} | {r['observed_rate']} |")
    mp = ea["missed_no_shows_profile"]
    lines += [
        "",
        f"**Missed no-shows (false negatives): {mp['count']}.** {mp['share_with_reminder']:.0%} had a reminder, "
        f"median lead time {mp['median_lead_time_days']:.0f} days, {mp['share_zero_prior_no_shows']:.0%} had no prior no-shows. "
        "These look like reliable patients, so the model has little signal for them.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=config.N_ROWS)
    args = parser.parse_args()
    m = run(n_rows=args.rows)
    sel = m["selected_model"]
    print(f"selected {sel}; test ROC-AUC {m['test_metrics'][sel]['roc_auc']}, PR-AUC {m['test_metrics'][sel]['pr_auc']}")
    print(f"artifact sha256 {m['artifact_sha256']}")


if __name__ == "__main__":
    main()
