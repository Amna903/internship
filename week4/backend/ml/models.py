"""Every candidate model, each a complete Pipeline: Step 3 preprocessing followed by a classifier.

The grid is small and fixed in advance on purpose: quick to run, easy to explain, and too small to
overfit the validation set by trying hundreds of settings.
"""

from dataclasses import dataclass

from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from . import config
from .preprocess import build_preprocessor


@dataclass(frozen=True)
class Candidate:
    family: str  # floor | baseline | improved
    name: str
    engineered: bool
    # A tuple of (name, value) pairs rather than a dict, so a Candidate can be a dictionary key.
    params: tuple = ()
    # Simpler models win ties: logistic regression's weights can be read and explained.
    complexity: int = 0

    @property
    def label(self) -> str:
        settings = ", ".join(f"{k}={v}" for k, v in self.params)
        return f"{self.name} ({settings})" if settings else self.name


def _classifier(candidate: Candidate):
    if candidate.name == "floor_dummy":
        # Always predicts the training no-show rate. Any real model must beat it.
        return DummyClassifier(strategy="prior")
    if candidate.name.startswith("logreg"):
        # No class_weight="balanced": it would inflate every probability and break "16% means 16%".
        # Imbalance is handled by the metric (PR-AUC) and the decision threshold instead.
        return LogisticRegression(max_iter=5000, random_state=config.SEED, **dict(candidate.params))
    if candidate.name == "gradient_boosting":
        # early_stopping=False: the automatic early stopping would carve its own random validation
        # set out of the training rows (ignoring patient groups) and add a second source of randomness.
        return HistGradientBoostingClassifier(max_iter=200, early_stopping=False, random_state=config.SEED,
                                              **dict(candidate.params))
    raise ValueError(f"Unknown candidate {candidate.name!r}")


def build(candidate: Candidate) -> Pipeline:
    return Pipeline([
        ("preprocess", build_preprocessor(engineered=candidate.engineered)),
        ("model", _classifier(candidate)),
    ])


C_GRID = [0.1, 1.0, 10.0]
BOOSTING_GRID = [(("learning_rate", lr), ("max_depth", depth)) for lr in (0.05, 0.1) for depth in (3, 6)]

CANDIDATES: list[Candidate] = (
    [Candidate("floor", "floor_dummy", engineered=False)]
    + [Candidate("baseline", "logreg_raw", engineered=False, params=(("C", c),)) for c in C_GRID]
    + [Candidate("improved", "logreg_engineered", engineered=True, params=(("C", c),), complexity=1) for c in C_GRID]
    + [Candidate("improved", "gradient_boosting", engineered=True, params=p, complexity=2) for p in BOOSTING_GRID]
)
