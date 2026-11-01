"""Acceptance check A1 as one command: rebuild everything from scratch and compare with what is committed.

Run:  python -m ml.verify_release      (exit code 0 = reproduced, 1 = something differs)

It regenerates the dataset, the three reports and the model release in a temporary folder, then checks:
  level 1  dataset SHA-256 equals the one recorded in the committed metadata
  level 2  eda.md, release-<version>.md and errors.md are identical; tuning.json has the same choice exactly,
           CV means and bar within 0.002, single fold scores within 0.01; tuning.md, metrics.md and
           explain.md have the same text and choice, with scores within 0.002 and cut-off figures within 0.005
           (forests differ slightly between CPUs); metadata metrics, threshold, schema, seed and
           estimator are identical
  level 3  the rebuilt and the committed model give the same probabilities (within 1e-9)
  level 4  the .joblib file is byte-identical, checked only on the platform and library versions that
           built the committed file (floating-point bits can differ across CPUs); reported as skipped
           elsewhere
CI runs this as its own job, so the check is visible on every push.
"""

import json
import math
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import artifact, config, eda, errors, explain, train, tune
from .models import GRID_CANDIDATES
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
# Where cut-off figures live: the decision-threshold section, and the per-algorithm confusion matrices.
CUTOFF_SECTIONS = [("## 3. Decision threshold", "## 4."),
                   ("### Confusion matrix for each algorithm", "**About this test set.**")]
# Confusion-matrix counts (TP, FP, FN, TN) move with the cut-off. Their tolerance is DERIVED from the same
# CUTOFF_TOLERANCE, applied to the rate each count belongs to, using the committed row's own totals:
#   TP, FN count no-shows: recall = TP / no-shows, so TP and FN may move floor(0.005 x no-shows) rows
#     (650 no-shows -> 3 rows).
#   FP, TN count attenders: false-positive rate = FP / attenders, so FP and TN may move
#     floor(0.005 x attenders) rows (3,302 attenders -> 16 rows).
# The two agree: a cut-off step flags appointments of both kinds, ~84% of them attenders, so FP moves about
# five times as much as TP, the same ratio as 16 : 3. Measured Mac vs Linux so far: recall 0.004 on
# validation, about 3 of 646 no-shows. Rounded down, so the derived bar is never looser than 0.005.
CONFUSION_COLUMNS = ("tp", "fp", "fn", "tn")


def confusion_count_tolerances(cells: list[str]) -> dict[str, int]:
    """For one confusion-matrix row (cells: model, cut-off, TP, FP, FN, TN, ...), rows each count may move."""
    tp, fp, fn, tn = (int(c.replace(",", "")) for c in cells[2:6])
    no_shows, attenders = tp + fn, fp + tn
    return {"tp": math.floor(CUTOFF_TOLERANCE * no_shows), "fn": math.floor(CUTOFF_TOLERANCE * no_shows),
            "fp": math.floor(CUTOFF_TOLERANCE * attenders), "tn": math.floor(CUTOFF_TOLERANCE * attenders)}


def _is_confusion_row(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return line.startswith("|") and len(cells) == 11 and all(re.fullmatch(r"[\d,]+", c) for c in cells[2:6])
# Whole-percent "gap closed" column: rounded from PR-AUC, so a 0.001 move can flip the last digit.
PERCENT_TOLERANCE = 1


def _allowed(token: str, in_cutoff_section: bool) -> float:
    decimal_tolerance = CUTOFF_TOLERANCE if in_cutoff_section else SCORE_TOLERANCE
    if token.endswith("%"):
        return 100 * decimal_tolerance if "." in token else PERCENT_TOLERANCE  # "33.5%": percentage points
    return decimal_tolerance if "." in token else 0  # whole numbers are exact (confusion counts handled apart)


def reports_match(committed: str, rebuilt: str) -> tuple[bool, str]:
    """Same text with numbers masked, and every number within its tolerance. Returns (ok, reason)."""
    if committed == rebuilt:
        return True, "identical"
    if NUMBER.sub("#", committed) != NUMBER.sub("#", rebuilt):
        return False, "text differs (a word, a model name or the choice changed)"
    worst = {"scores": 0.0, "cut-off figures": 0.0}
    in_cutoff = False
    for line_a, line_b in zip(committed.splitlines(), rebuilt.splitlines()):
        if any(line_a.startswith(start) for start, _ in CUTOFF_SECTIONS):
            in_cutoff = True
        elif any(line_a.startswith(end) for _, end in CUTOFF_SECTIONS):
            in_cutoff = False
        counts = {}
        if in_cutoff and _is_confusion_row(line_a):
            cells_a = [c.strip() for c in line_a.strip().strip("|").split("|")]
            cells_b = [c.strip() for c in line_b.strip().strip("|").split("|")]
            allowed_rows = confusion_count_tolerances(cells_a)
            for name, a, b in zip(CONFUSION_COLUMNS, cells_a[2:6], cells_b[2:6]):
                moved = abs(int(a.replace(",", "")) - int(b.replace(",", "")))
                if moved > allowed_rows[name]:
                    return False, f"{name.upper()} {a} became {b} (allowed {allowed_rows[name]} rows)"
            # positions of the four counts among the line's numbers (the model name may contain numbers too)
            first = sum(len(NUMBER.findall(c)) for c in cells_a[:2])
            counts = set(range(first, first + 4))
        for i, (a, b) in enumerate(zip(NUMBER.findall(line_a), NUMBER.findall(line_b))):
            if i in counts:
                continue  # checked above with its derived tolerance
            x, y = float(a.rstrip("%").replace(",", "")), float(b.rstrip("%").replace(",", ""))
            if abs(x - y) > _allowed(a, in_cutoff):
                return False, f"{a} became {b}" + (" (cut-off figure)" if in_cutoff else " (score)")
            if "." in a and not a.endswith("%"):
                kind = "cut-off figures" if in_cutoff else "scores"
                worst[kind] = max(worst[kind], abs(x - y))
    return True, (f"same text and choice; scores within {SCORE_TOLERANCE} (largest {worst['scores']:.3f}), "
                  f"cut-off figures within {CUTOFF_TOLERANCE} (largest {worst['cut-off figures']:.3f})")


# Tolerances for a rebuilt search, by what each number is used for. CI measured on Linux vs Mac: means moved
# at most 0.0009, single fold scores up to 0.0033, the bar 0.0002.
# The chosen setting decides the model: it must be EXACTLY the same.
# CV means and the one-standard-error bar are what the rule compares: averages over the whole train part,
# so a forest's platform noise moves them about 0.001. Same strict bar as other scores.
TUNING_MEAN_TOLERANCE = SCORE_TOLERANCE
# A single fold score is computed on a fifth of the rows (~2,400), so its noise is about sqrt(5) = 2.2 times
# larger than a mean's, and no decision reads it on its own. Loose sanity bar: a large drift still fails.
TUNING_FOLD_TOLERANCE = 0.01


def tuning_matches(committed: dict, rebuilt: dict) -> tuple[bool, str]:
    """Same design and choice exactly; means and bar strictly; single fold scores only loosely."""
    for key in ["seed", "n_splits", "n_iter", "train_rows", "search_space", "chosen"]:
        if committed[key] != rebuilt[key]:
            return False, f"{key} differs: {committed[key]} became {rebuilt[key]}"
    a_rows = [(json.dumps(x["params"]), x) for x in committed["search"]] + [(g["label"], g) for g in committed["grid_cv"]]
    b_rows = [(json.dumps(x["params"]), x) for x in rebuilt["search"]] + [(g["label"], g) for g in rebuilt["grid_cv"]]
    if [k for k, _ in a_rows] != [k for k, _ in b_rows]:
        return False, "different settings were drawn or cross-validated"
    if abs(committed["bar"] - rebuilt["bar"]) > TUNING_MEAN_TOLERANCE:
        return False, f"one-SE bar {committed['bar']:.4f} became {rebuilt['bar']:.4f}"
    worst_mean = worst_fold = 0.0
    for (key, a), (_, b) in zip(a_rows, b_rows):
        mean_move = abs(a["mean"] - b["mean"])
        if mean_move > TUNING_MEAN_TOLERANCE:
            return False, f"CV mean of {key} {a['mean']:.4f} became {b['mean']:.4f}"
        fold_move = max(abs(x - y) for x, y in zip(a["fold_scores"], b["fold_scores"]))
        if fold_move > TUNING_FOLD_TOLERANCE:
            return False, f"a fold score of {key} moved {fold_move:.4f}"
        worst_mean, worst_fold = max(worst_mean, mean_move), max(worst_fold, fold_move)
    return True, (f"same choice; means and bar within {TUNING_MEAN_TOLERANCE} (largest {worst_mean:.4f}), "
                  f"fold scores within {TUNING_FOLD_TOLERANCE} (largest {worst_fold:.4f})")


def tuning_diagnostics(committed: dict, rebuilt: dict) -> str:
    """Facts about a rebuilt search, printed whether or not the checks pass: same choice? how far did the
    means (what the rule uses) and single fold scores move? did any setting cross the one-SE bar?"""
    def means(r):
        return {json.dumps(x["params"]): x["mean"] for x in r["search"]} | {g["label"]: g["mean"] for g in r["grid_cv"]}

    def folds(r):
        return {json.dumps(x["params"]): x["fold_scores"] for x in r["search"]} | {g["label"]: g["fold_scores"]
                                                                                    for g in r["grid_cv"]}

    m_a, m_b, f_a, f_b = means(committed), means(rebuilt), folds(committed), folds(rebuilt)
    mean_diff = max(abs(m_a[k] - m_b[k]) for k in m_a)
    fold_diff = max(abs(x - y) for k in f_a for x, y in zip(f_a[k], f_b[k]))
    eligible = [{json.dumps(x["params"]) for x in r["search"] if x["mean"] >= r["bar"]} for r in (committed, rebuilt)]
    return (f"INFO  tuning: same choice: {committed['chosen'] == rebuilt['chosen']} "
            f"(committed {committed['chosen']}, rebuilt {rebuilt['chosen']}); largest move of a mean "
            f"{mean_diff:.4f}, of a single fold score {fold_diff:.4f}; bar {committed['bar']:.4f} -> "
            f"{rebuilt['bar']:.4f}; settings crossing the bar: {len(eligible[0] ^ eligible[1])}")


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
    tuning = tune.run(df)
    committed_tuning = json.loads(tune.RESULT.read_text())
    ok, reason = tuning_matches(committed_tuning, tuning)
    checks.append(("2", f"tuning.json (30-draw search) regenerated: {reason}", ok))
    print(tuning_diagnostics(committed_tuning, tuning))
    step2 = train.run(df, candidates=GRID_CANDIDATES, score_test=False)
    # The report is rebuilt from the COMMITTED result (checked against the rebuilt one just above, within
    # tolerance), so near-tied forests can't change which settings the report names on another machine.
    ok, reason = reports_match(tune.REPORT.read_text(), tune.build_report(
        committed_tuning, {c.label: s.pr_auc for c, s in step2.validation.items()}))
    checks.append(("2", f"tuning.md regenerated: {reason}", ok))
    ok, reason = reports_match(train.REPORT.read_text(), train.comparison_report(df))
    checks.append(("2", f"metrics.md regenerated: {reason}", ok))
    ok, reason = reports_match(explain.REPORT.read_text(), explain.build_report(explain.analyse(df)))
    checks.append(("2", f"explain.md regenerated: {reason}", ok))

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
