"""Build the release: the chosen pipeline as one .joblib file plus a .json metadata file.

Run:  python -m ml.artifact      (writes ml/artifacts/no-show-<version>.joblib and .json)

Both files are committed, so the API works straight after cloning. The metadata has no timestamp on
purpose: rebuilding must produce identical files, and git history already records when.
"""

import hashlib
import json
import platform
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import scipy
import sklearn

from . import config, train


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_paths(directory: Path = config.ARTIFACT_DIR, version: str = config.MODEL_VERSION) -> tuple[Path, Path]:
    stem = f"{config.MODEL_NAME}-{version}"
    return directory / f"{stem}.joblib", directory / f"{stem}.json"


def library_versions() -> dict:
    return {"python": platform.python_version(), "scikit-learn": sklearn.__version__, "numpy": np.__version__,
            "pandas": pd.__version__, "scipy": scipy.__version__, "joblib": joblib.__version__}


def _scores(s: train.Scores) -> dict:
    return {"pr_auc": round(s.pr_auc, 6), "roc_auc": round(s.roc_auc, 6), "brier": round(s.brier, 6)}


def build(directory: Path = config.ARTIFACT_DIR) -> dict:
    result = train.run()
    model_path, meta_path = artifact_paths(directory)
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(result.chosen_pipeline, model_path)

    chosen_test = next(s for k, s in result.test.items() if k.startswith("chosen"))
    metadata = {
        "model": f"{config.MODEL_NAME}-{config.MODEL_VERSION}",
        "version": config.MODEL_VERSION,
        "task": "Synthetic appointment no-show likelihood (binary). Not diagnostic.",
        "disclaimer": config.DISCLAIMER,
        "estimator": result.chosen.label,
        "seed": config.SEED,
        "training_data": {"sha256": result.data_sha256, "split_rows": result.split_sizes, "generator": "ml/data.py",
                          # shown next to each estimate as the average to compare with
                          "average_no_show_rate": round(result.train_no_show_rate, 6)},
        "features": config.FEATURE_SCHEMA,
        "decision": {"threshold": round(result.threshold.value, 6),
                     "rule": "probability >= threshold -> extra_reminder_suggested, else standard_reminder",
                     "actions": config.ACTIONS},
        "metrics": {"validation": _scores(result.validation[result.chosen]), "test": _scores(chosen_test),
                    "test_threshold": {"precision": round(result.test_threshold.precision, 6),
                                       "recall": round(result.test_threshold.recall, 6)},
                    "report": "ml/reports/metrics.md"},
        "libraries": library_versions(),
        "built_on": {"platform": sys.platform, "machine": platform.machine()},
        "artifact_sha256": file_sha256(model_path),
    }
    meta_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    return metadata


def main():
    metadata = build()
    print(f"model:      {metadata['model']} ({metadata['estimator']})")
    print(f"sha256:     {metadata['artifact_sha256']}")
    print(f"test:       PR-AUC {metadata['metrics']['test']['pr_auc']:.3f} · ROC-AUC {metadata['metrics']['test']['roc_auc']:.3f}")
    print(f"threshold:  {metadata['decision']['threshold']}")
    print(f"written to: {config.ARTIFACT_DIR}")


if __name__ == "__main__":
    main()
