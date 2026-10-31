"""Acceptance check A1 as one command: rebuild everything from scratch and compare with what is committed.

Run:  python -m ml.verify_release      (exit code 0 = reproduced, 1 = something differs)

It regenerates the dataset, the three reports and the model release in a temporary folder, then checks:
  level 1  dataset SHA-256 equals the one recorded in the committed metadata
  level 2  eda.md, release-<version>.md and errors.md are identical; metrics.md has the same text and
           choice; scores within 0.002, cut-off figures within 0.005 (forests differ slightly between CPUs); metadata metrics, threshold, schema, seed
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
# between CPUs (arm64 vs x86). The comparison report is therefore checked in two ways: the text (every
# word, model name and the choice) must be identical, and every number must agree within a tolerance that
# depends on the KIND of number. Reports holding the served release must match exactly.
NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")

# PR-AUC, ROC-AUC, Brier (and train/out-of-bag/gap figures built from them): averages over thousands of
# rows, so a forest's platform noise moves them by about 0.001. Kept strict.
SCORE_TOLERANCE = 0.002
# Threshold, precision, recall, F1 and share flagged (section 3): read at the F1-best cut-off, which is a
# staircase. A 0.001 shift in probabilities can move the cut-off one step and flag 2-3 appointments
# differently; CI measured recall 0.526 -> 0.522. Only these are allowed the looser bar, equal to the
# tie margin that model selection already treats as noise.
CUTOFF_TOLERANCE = train.TIE_MARGIN
CUTOFF_SECTION = ("## 3. Decision threshold", "## 4.")
# Whole-percent "gap closed" column: rounded from PR-AUC, so a 0.001 move can flip the last digit.
PERCENT_TOLERANCE = 1


def _allowed(token: str, in_cutoff_section: bool) -> float:
    decimal_tolerance = CUTOFF_TOLERANCE if in_cutoff_section else SCORE_TOLERANCE
    if token.endswith("%"):
        return 100 * decimal_tolerance if "." in token else PERCENT_TOLERANCE  # "33.5%": percentage points
    return decimal_tolerance if "." in token else 0  # whole numbers (row counts, seeds) must be exact


def reports_match(committed: str, rebuilt: str) -> tuple[bool, str]:
    """Same text with numbers masked, and every number within its tolerance. Returns (ok, reason)."""
    if committed == rebuilt:
        return True, "identical"
    if NUMBER.sub("#", committed) != NUMBER.sub("#", rebuilt):
        return False, "text differs (a word, a model name or the choice changed)"
    worst = {"scores": 0.0, "cut-off figures": 0.0}
    in_cutoff = False
    for line_a, line_b in zip(committed.splitlines(), rebuilt.splitlines()):
        if line_a.startswith(CUTOFF_SECTION[0]):
            in_cutoff = True
        elif line_a.startswith(CUTOFF_SECTION[1]):
            in_cutoff = False
        for a, b in zip(NUMBER.findall(line_a), NUMBER.findall(line_b)):
            x, y = float(a.rstrip("%").replace(",", "")), float(b.rstrip("%").replace(",", ""))
            if abs(x - y) > _allowed(a, in_cutoff):
                return False, f"{a} became {b}" + (" (cut-off figure)" if in_cutoff else " (score)")
            if "." in a and not a.endswith("%"):
                kind = "cut-off figures" if in_cutoff else "scores"
                worst[kind] = max(worst[kind], abs(x - y))
    return True, (f"same text and choice; scores within {SCORE_TOLERANCE} (largest {worst['scores']:.3f}), "
                  f"cut-off figures within {CUTOFF_TOLERANCE} (largest {worst['cut-off figures']:.3f})")


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
