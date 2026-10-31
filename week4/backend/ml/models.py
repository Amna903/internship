"""Every candidate model, each a complete Pipeline: Step 3 preprocessing followed by a classifier.

The grid is small and fixed in advance on purpose: quick to run, easy to explain, and too small to
overfit the validation set by trying hundreds of settings.
"""

from dataclasses import dataclass

from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
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
    # Simpler models win ties; see SIMPLICITY_ORDER below. Fixed before training.
    complexity: int = 0

    @property
    def within_family_simplicity(self) -> tuple:
        """Tie-break between settings of the SAME family (lower = simpler), applied after `complexity`.

        Random forest: shallower trees first, then larger leaves; both limit how much a tree can memorise.
        The number of trees does not cause overfitting (more trees only make the vote steadier), so on a
        remaining tie MORE trees win. Other families have no within-family order: highest score wins.
        """
        if self.name != "random_forest":
            return ()
        p = dict(self.params)
        depth = p.get("max_depth")
        return (float("inf") if depth is None else depth, -p.get("min_samples_leaf", 1),
                -p.get("n_estimators", RF_TREES))

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
    if candidate.name == "random_forest":
        # oob_score=True: each tree skips about a third of the rows, and scoring every row only with the
        # trees that never saw it gives a fair training-time estimate. A forest's plain training score is
        # always near perfect, because its trees memorise the rows they were grown on.
        # No class_weight, for the same reason as logistic regression.
        # n_jobs=1: with several threads, predict_proba adds the trees' outputs in whatever order the threads
        # finish, so repeated runs differ in the last digits, enough to flip a near-tie between two forests.
        return RandomForestClassifier(n_estimators=RF_TREES, oob_score=True, n_jobs=1, random_state=config.SEED,
                                      **dict(candidate.params))
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


# Tie-break order, written before training (lower = simpler = wins a tie):
#   0 logistic regression, raw inputs: few weights, each one readable
#   1 logistic regression + engineered features: still readable weights, four more of them
#   2 random forest: many trees, but each grown independently and averaged; two settings
#   3 gradient boosting: trees built in sequence, each correcting the last; settings interact
SIMPLICITY_ORDER = ["logreg_raw", "logreg_engineered", "random_forest", "gradient_boosting"]

RF_TREES = 300
C_GRID = [0.1, 1.0, 10.0]
FOREST_GRID = [(("max_depth", depth), ("min_samples_leaf", leaf)) for depth in (6, 10, None) for leaf in (20, 50)]
BOOSTING_GRID = [(("learning_rate", lr), ("max_depth", depth)) for lr in (0.05, 0.1) for depth in (3, 6)]

CANDIDATES: list[Candidate] = (
    [Candidate("floor", "floor_dummy", engineered=False)]
    + [Candidate("baseline", "logreg_raw", engineered=False, params=(("C", c),)) for c in C_GRID]
    + [Candidate("improved", "logreg_engineered", engineered=True, params=(("C", c),), complexity=1) for c in C_GRID]
    + [Candidate("improved", "random_forest", engineered=True, params=p, complexity=2) for p in FOREST_GRID]
    + [Candidate("improved", "gradient_boosting", engineered=True, params=p, complexity=3) for p in BOOSTING_GRID]
)

# The served release (v1.0.0) was chosen from Week 3's candidates. Until Step 4 releases a new version,
# the release and its error report are rebuilt from this list, so v1.0.0 stays exactly reproducible
# while metrics.md compares every model.
RELEASE_CANDIDATES: list[Candidate] = [c for c in CANDIDATES if c.name != "random_forest"]
