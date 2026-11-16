"""The champion/challenger release rule, FROZEN on 2026-11-01 (mentor review on PR #1), before any
evaluation of a future challenger. Changing it later would need a new, dated decision recorded in
docs/REQUIREMENTS.md, made before that evaluation; `tests/test_release_rule.py` pins its behaviour.

Why it exists: in Week 4 a test result informed the release decision, after which that test set could no
longer give a clean estimate. Writing the rule down first, and judging it on a fresh holdout
(`ml/holdout.py`), keeps the next release decision independent of the evidence used to judge it.

The rule:
  1. The served model is the champion. A challenger replaces it only if, on the same training folds, its
     mean CV PR-AUC beats the champion's by MORE than one standard error of the champion's mean.
  2. The simplicity preference applies only between model families that differ in explainability
     (logistic regression before trees). Between equally explainable models, the higher CV mean wins.
  3. The decision is made on CV before any held-out data is scored. The holdout score is then reported
     for the decided model; it is never used to choose.
  4. Version numbers: same inputs, retrained -> minor; inputs change -> major.
"""

import math

import numpy as np

FROZEN_ON = "2026-11-01"

# Families in the same group are equally explainable; groups are ordered from most to least explainable.
EXPLAINABILITY_GROUPS = [{"logreg_raw", "logreg_engineered"}, {"random_forest", "gradient_boosting"}]


def explainability(name: str) -> int:
    return next(i for i, group in enumerate(EXPLAINABILITY_GROUPS) if name in group)


def challenger_wins(champion_folds, challenger_folds) -> bool:
    """Rule 1: replace the champion only on a lead larger than one standard error of the champion's mean."""
    champion_folds, challenger_folds = np.asarray(champion_folds, float), np.asarray(challenger_folds, float)
    if len(champion_folds) != len(challenger_folds):
        raise ValueError("champion and challenger must be scored on the same folds")
    se = float(np.std(champion_folds, ddof=1)) / math.sqrt(len(champion_folds))
    return float(challenger_folds.mean() - champion_folds.mean()) > se


def simplicity_applies(name_a: str, name_b: str) -> bool:
    """Rule 2: the simplicity preference only separates models that differ in explainability."""
    return explainability(name_a) != explainability(name_b)


def next_version(current: str, inputs_changed: bool) -> str:
    """Rule 4."""
    major, minor, _ = (int(x) for x in current.split("."))
    return f"{major + 1}.0.0" if inputs_changed else f"{major}.{minor + 1}.0"
