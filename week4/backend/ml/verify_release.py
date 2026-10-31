"""Acceptance check A1 as one command: rebuild everything from scratch and compare with what is committed.

Run:  python -m ml.verify_release      (exit code 0 = reproduced, 1 = something differs)

It regenerates the dataset, the three reports and the model release in a temporary folder, then checks:
  level 1  dataset SHA-256 equals the one recorded in the committed metadata
  level 2  eda.md, metrics.md, release-<version>.md and errors.md are identical; metadata metrics, threshold, schema, seed
           and estimator are identical
  level 3  the rebuilt and the committed model give the same probabilities (within 1e-9)
  level 4  the .joblib file is byte-identical, checked only on the platform and library versions that
           built the committed file (floating-point bits can differ across CPUs); reported as skipped
           elsewhere
CI runs this as its own job, so the check is visible on every push.
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import artifact, config, eda, errors, train
from .data import dataset_hash, generate
from .inference import load
from .preprocess import model_input
from .split import split

COMPARED_METADATA_KEYS = ["model", "version", "estimator", "seed", "features", "decision", "metrics", "training_data",
                          "task", "disclaimer"]


def compare_metadata(committed: dict, rebuilt: dict) -> list[str]:
    """Names of the metadata sections that differ (empty list = identical)."""
    return [key for key in COMPARED_METADATA_KEYS if committed.get(key) != rebuilt.get(key)]


def main() -> int:
    checks: list[tuple[str, str, bool | None]] = []

    df = generate()
    committed_meta = json.loads(artifact.artifact_paths()[1].read_text())
    checks.append(("1", "dataset SHA-256 equals the committed metadata",
                   dataset_hash(df) == committed_meta["training_data"]["sha256"]))

    checks.append(("2", f"{train.RELEASE_REPORT.name} regenerated identically",
                   train.RELEASE_REPORT.read_text() == train.release_report(df)))
    for name, module, build in [("eda.md", eda, lambda: eda.build_report(df)),
                                ("metrics.md", train, lambda: train.comparison_report(df)),
                                ("errors.md", errors, lambda: errors.build_report(errors.analyse(df)))]:
        checks.append(("2", f"{name} regenerated identically", module.REPORT.read_text() == build()))

    with tempfile.TemporaryDirectory() as tmp:
        rebuilt_dir = Path(tmp)
        rebuilt_meta = artifact.build(rebuilt_dir)
        differing = compare_metadata(committed_meta, rebuilt_meta)
        checks.append(("2", "metadata identical (" + (", ".join(differing) if differing else
                                                      "metrics, threshold, schema, seed, estimator") + ")", not differing))

        rows = model_input(split(df)[2])
        committed_p = load().pipeline.predict_proba(rows)[:, 1]
        rebuilt_p = load(rebuilt_dir).pipeline.predict_proba(rows)[:, 1]
        largest = float(np.max(np.abs(committed_p - rebuilt_p)))
        checks.append(("3", f"same probabilities on {len(rows):,} test rows (largest difference {largest:.1e})",
                       largest <= 1e-9))

        same_platform = (rebuilt_meta["built_on"] == committed_meta["built_on"]
                         and rebuilt_meta["libraries"] == committed_meta["libraries"])
        if same_platform:
            checks.append(("4", "model file byte-identical",
                           rebuilt_meta["artifact_sha256"] == committed_meta["artifact_sha256"]))
        else:
            checks.append(("4", f"byte identity not checked: committed file built on {committed_meta['built_on']}, "
                                f"this run on {rebuilt_meta['built_on']}", None))

    for level, name, ok in checks:
        print(f"{'PASS' if ok else 'SKIP' if ok is None else 'FAIL'}  level {level}  {name}")
    failed = [name for _, name, ok in checks if ok is False]
    print(f"\n{config.MODEL_NAME}-{config.MODEL_VERSION}: " +
          ("reproduced" if not failed else f"NOT reproduced ({len(failed)} check(s) failed)"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
