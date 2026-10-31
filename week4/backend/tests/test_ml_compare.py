"""Week 4 Step 2 evidence (S3, S4, S5, S8): three algorithms compared on validation, a train versus
validation table with an overfitting warning, a simplicity order fixed before training, and no test
score anywhere in the comparison."""

import numpy as np
import pytest

from ml import config, train
from ml.data import generate
from ml.models import CANDIDATES, SIMPLICITY_ORDER, Candidate, build
from ml.preprocess import model_input
from ml.split import split
from ml.verify_release import reports_match


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def comparison(df):
    return train.run(df, score_test=False)


def forests(result):
    return [c for c in result.validation if c.name == "random_forest"]


# ---- Three algorithms ----

def test_logistic_regression_random_forest_and_gradient_boosting_are_all_trained(comparison):
    trained = {c.name for c in comparison.validation}
    assert {"logreg_raw", "logreg_engineered", "random_forest", "gradient_boosting"} <= trained


def test_random_forest_uses_the_seed_no_class_weight_and_out_of_bag_scoring():
    forest = build(next(c for c in CANDIDATES if c.name == "random_forest")).named_steps["model"]
    assert forest.random_state == config.SEED
    assert forest.class_weight is None
    assert forest.oob_score is True


def test_random_forest_gives_identical_probabilities_when_trained_twice(df):
    """Run with several threads, the forest adds tree outputs in a varying order and the last digits
    change; n_jobs=1 makes it exact."""
    train_rows, validation, _ = split(df)
    candidate = next(c for c in CANDIDATES if c.name == "random_forest")
    X, y, X_val = model_input(train_rows), train_rows[config.LABEL], model_input(validation)
    first, second = (build(candidate).fit(X, y).predict_proba(X_val) for _ in range(2))
    np.testing.assert_array_equal(first, second)


# ---- Simplicity order, fixed before training ----

def test_complexity_follows_the_written_simplicity_order():
    rank = {name: i for i, name in enumerate(SIMPLICITY_ORDER)}
    for c in CANDIDATES:
        if c.family != "floor":
            assert c.complexity == rank[c.name], c.label


def test_a_tie_between_forest_and_boosting_goes_to_the_forest():
    forest = Candidate("improved", "random_forest", True, (), complexity=2)
    boosting = Candidate("improved", "gradient_boosting", True, (), complexity=3)
    scores = {forest: train.Scores(0.300, 0.7, 0.12, 0.16), boosting: train.Scores(0.304, 0.7, 0.12, 0.16)}
    assert train.select(scores) == forest


# ---- Train versus validation ----

def test_train_and_out_of_bag_scores_exist_for_the_right_models(comparison):
    assert set(comparison.train) == set(comparison.validation)
    assert set(comparison.out_of_bag) == set(forests(comparison))


def test_train_scores_are_really_computed_on_the_training_rows(df, comparison):
    train_rows, _, _ = split(df)
    c = comparison.chosen
    expected = train.score(train_rows[config.LABEL], comparison.fitted[c].predict_proba(model_input(train_rows))[:, 1])
    assert comparison.train[c] == expected


def test_report_table_states_every_models_train_validation_and_gap(comparison):
    report = train.build_report(comparison)
    for c in comparison.validation:
        if c.family == "floor":
            continue
        tr, va = comparison.train[c], comparison.validation[c]
        assert f"| {c.label} | {tr.pr_auc:.3f} | {va.pr_auc:.3f} | {tr.pr_auc - va.pr_auc:+.3f} |" in report


@pytest.mark.parametrize("train_pr, val_pr, warned", [(0.40, 0.30, True), (0.33, 0.30, False), (0.35, 0.30, False)])
def test_overfit_warning_threshold(train_pr, val_pr, warned):
    assert train.overfit_warning(train.Scores(train_pr, 0.7, 0.1, 0.16), train.Scores(val_pr, 0.7, 0.1, 0.16)) is warned


def test_warning_fires_on_a_tree_built_to_memorise_and_not_on_the_floor(df):
    from sklearn.pipeline import Pipeline
    from sklearn.tree import DecisionTreeClassifier

    from ml.preprocess import build_preprocessor

    train_rows, validation, _ = split(df)
    X, y = model_input(train_rows), train_rows[config.LABEL]
    X_val, y_val = model_input(validation), validation[config.LABEL]
    memoriser = Pipeline([("preprocess", build_preprocessor(engineered=True)),
                          ("model", DecisionTreeClassifier(min_samples_leaf=1, random_state=config.SEED))]).fit(X, y)
    floor = build(next(c for c in CANDIDATES if c.family == "floor")).fit(X, y)
    for model, expected in [(memoriser, True), (floor, False)]:
        tr = train.score(y, model.predict_proba(X)[:, 1])
        va = train.score(y_val, model.predict_proba(X_val)[:, 1])
        assert train.overfit_warning(tr, va) is expected


def test_forests_out_of_bag_score_is_a_fairer_estimate_than_their_training_score(comparison):
    """The point of the out-of-bag column: it lands near validation, while training score runs ahead."""
    for c in forests(comparison):
        tr, oob, va = comparison.train[c], comparison.out_of_bag[c], comparison.validation[c]
        assert abs(oob.pr_auc - va.pr_auc) < abs(tr.pr_auc - va.pr_auc), c.label


def test_report_says_the_warning_is_not_a_verdict(comparison):
    report = train.build_report(comparison)
    assert "a warning, not a verdict" in report
    assert "out-of-bag" in report


# ---- No test numbers until the final evaluation step ----

def test_comparison_never_scores_the_test_set(comparison):
    assert comparison.test == {} and comparison.test_threshold is None and comparison.improvement is None
    report = train.build_report(comparison)
    assert "## 4. Test set: not scored yet" in report
    assert "applied once" not in report


def test_committed_comparison_report_is_up_to_date(comparison):
    ok, reason = reports_match(train.REPORT.read_text(), train.build_report(comparison))
    assert ok, reason


# ---- Same choice on every machine ----

def test_within_family_order_is_depth_then_leaf_then_more_trees():
    def forest(depth, leaf, trees=300):
        return Candidate("improved", "random_forest", True,
                         (("max_depth", depth), ("min_samples_leaf", leaf), ("n_estimators", trees)), complexity=2)
    ordered = [forest(6, 50), forest(6, 20), forest(10, 50), forest(None, 50)]
    assert sorted(reversed(ordered), key=lambda c: c.within_family_simplicity) == ordered
    # More trees only steady the vote, they don't memorise: on a remaining tie, more trees win.
    assert forest(6, 50, 500).within_family_simplicity < forest(6, 50, 100).within_family_simplicity


def test_near_tied_forests_resolve_to_the_simpler_one_whatever_their_order():
    """The CI finding: two forests 0.0002 apart swapped places between Mac and Linux. With the
    within-family rule, a swap of near-tied scores can't change the choice."""
    deep = Candidate("improved", "random_forest", True, (("max_depth", None), ("min_samples_leaf", 50)), complexity=2)
    shallow = Candidate("improved", "random_forest", True, (("max_depth", 6), ("min_samples_leaf", 50)), complexity=2)
    for deep_score, shallow_score in [(0.2845, 0.281), (0.281, 0.2845)]:
        scores = {deep: train.Scores(deep_score, 0.65, 0.13, 0.16), shallow: train.Scores(shallow_score, 0.65, 0.13, 0.16)}
        assert train.select(scores) == shallow


def test_report_check_tolerates_platform_noise_but_not_a_different_choice():
    committed = "**Chosen: random_forest (max_depth=6)** | 0.281 | 69% |"
    assert reports_match(committed, committed.replace("0.281", "0.282").replace("69%", "68%"))[0]
    assert not reports_match(committed, committed.replace("0.281", "0.290"))[0]
    assert not reports_match(committed, committed.replace("max_depth=6", "max_depth=10"))[0]
    assert not reports_match("12,126 rows", "12,127 rows")[0]
    # The real CI case: recall at the decision threshold moved by 0.004 between Mac and Linux.
    row = "| validation (where it was chosen) | 0.1879 | 0.254 | 0.526 | 0.342 | 33.5% |"
    assert reports_match(row, row.replace("0.526", "0.522").replace("33.5%", "33.3%"))[0]
    assert not reports_match(row, row.replace("33.5%", "34.5%"))[0]
