"""Acceptance check A1 as one command: rebuild everything from scratch and compare with what is committed.

Run:  python -m ml.verify_release      (exit code 0 = reproduced, 1 = something differs)

It regenerates the dataset, the three reports and the model release in a temporary folder, then checks:
  level 1  dataset SHA-256 equals the one recorded in the committed metadata
  level 2  eda.md, release-<version>.md and errors.md are identical; metrics.md has the same text and
           choice with numbers within 0.005 (random forests differ slightly between CPUs); metadata metrics, threshold, schema, seed
           and estimator are identical
  level 3  the rebuilt and the committed model give the same probabilities (within 1e-9)
  level 4  the .joblib file is byte-identical, checked only on the platform and library versions that
           built the committed file (floating-point bits can differ across CPUs); reported as skipped
           elsewhere
CI runs this as its own job, so the check is visible on every push.
"""

import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import artifact, config, eda, errors, train
from .data import dataset_hash, generate
from .inference import load
from .preprocess import model_input
from .split import split

# Random forests are built from thousands of threshold comparisons; the last floating-point digits differ
# between CPUs (arm64 vs x86), which can move a forest's score by about 0.001. Figures read at the decision
# threshold move more (CI measured 0.004 in recall): the F1-best cut-off is a staircase, so a tiny shift in
# probabilities can move it one step and flag 2-3 appointments differently. The comparison report is
# therefore checked in two ways: the text (every word, model name and the choice) must be identical, and
# every number must agree within TIE_MARGIN, the size of difference model selection already treats as
# noise. Reports holding the served release must match exactly.
NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")
DECIMAL_TOLERANCE = train.TIE_MARGIN
PERCENT_TOLERANCE = 1  # whole-percent columns ("69%") follow the decimals they are computed from


def reports_match(committed: str, rebuilt: str) -> tuple[bool, str]:
    """Same text with numbers masked, and every number within tolerance. Returns (ok, reason)."""
    if committed == rebuilt:
        return True, "identical"
    if NUMBER.sub("#", committed) != NUMBER.sub("#", rebuilt):
        return False, "text differs (a word, a model name or the choice changed)"
    worst = 0.0
    for a, b in zip(NUMBER.findall(committed), NUMBER.findall(rebuilt)):
        x, y = float(a.rstrip("%").replace(",", "")), float(b.rstrip("%").replace(",", ""))
        if a.endswith("%"):
            allowed = 100 * DECIMAL_TOLERANCE if "." in a else PERCENT_TOLERANCE  # "33.5%": 0.5 points
        else:
            allowed = DECIMAL_TOLERANCE if "." in a else 0
        if abs(x - y) > allowed:
            return False, f"{a} became {b}"
        if "." in a and not a.endswith("%"):
            worst = max(worst, abs(x - y))
    return True, f"same text and choice; numbers within {DECIMAL_TOLERANCE} (largest difference {worst:.3f})"


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
                                ("errors.md", errors, lambda: errors.build_report(errors.analyse(df)))]:
        checks.append(("2", f"{name} regenerated identically", module.REPORT.read_text() == build()))
    ok, reason = reports_match(train.REPORT.read_text(), train.comparison_report(df))
    checks.append(("2", f"metrics.md regenerated: {reason}", ok))

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
