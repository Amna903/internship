"""Step 4 evidence: models beat the floor, stay below the oracle, choices use validation only,
the test set is touched once, and training is deterministic."""

import inspect

import numpy as np
import pytest

from ml import config, train
from ml.data import generate
from ml.models import CANDIDATES, build
from ml.preprocess import model_input
from ml.split import split


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def result(df):
    return train.run(df)


def real(result):
    return {c: s for c, s in result.validation.items() if c.family != "floor"}


# ---- Sanity of the comparison ----

def test_every_real_model_beats_the_floor_on_validation(result):
    floor = next(s for c, s in result.validation.items() if c.family == "floor")
    for candidate, s in real(result).items():
        assert s.pr_auc > floor.pr_auc + 0.05, candidate.label
        assert s.roc_auc > 0.6, candidate.label


def test_no_model_beats_the_oracle_ceiling(result):
    # Beating perfect knowledge of the true probability would mean the model is seeing the answer.
    for candidate, s in result.validation.items():
        assert s.pr_auc < result.oracle_validation.pr_auc, candidate.label
        assert s.brier > result.oracle_validation.brier, candidate.label


def test_engineered_features_beat_the_raw_baseline(result):
    best = {name: max(s.pr_auc for c, s in result.validation.items() if c.name == name)
            for name in ("logreg_raw", "logreg_engineered")}
    assert best["logreg_engineered"] > best["logreg_raw"]


def test_the_grid_covers_floor_baseline_and_two_improved_families():
    assert {c.family for c in CANDIDATES} == {"floor", "baseline", "improved"}
    assert {c.name for c in CANDIDATES if c.family == "improved"} == {"logreg_engineered", "gradient_boosting"}


# ---- Selection and threshold use validation only ----

def test_choice_and_threshold_do_not_depend_on_test_labels(df, result):
    _, _, test = split(df)
    scrambled = df.copy()
    scrambled.loc[test.index, config.LABEL] = ~scrambled.loc[test.index, config.LABEL]  # flip every test label
    again = train.run(scrambled)
    assert again.chosen == result.chosen
    assert again.threshold.value == result.threshold.value
    assert again.test != result.test  # the test scores do react, so the test really used test rows


def test_selection_rule_prefers_the_simpler_model_on_a_tie():
    from ml.models import Candidate
    simple = Candidate("improved", "logreg_engineered", True, (("C", 1.0),), complexity=1)
    complex_ = Candidate("improved", "gradient_boosting", True, (), complexity=2)
    scores = {simple: train.Scores(0.300, 0.7, 0.12, 0.16), complex_: train.Scores(0.303, 0.7, 0.12, 0.16)}
    assert train.select(scores) == simple  # within TIE_MARGIN -> simpler wins
    scores[complex_] = train.Scores(0.320, 0.7, 0.12, 0.16)
    assert train.select(scores) == complex_  # clearly better -> it wins


def test_threshold_is_below_one_half_because_of_imbalance(result):
    assert 0.05 < result.threshold.value < 0.5


def test_test_set_is_scored_in_exactly_one_place():
    source = inspect.getsource(train)
    assert source.count("evaluate_on_test(") == 2  # the definition and its single call
    run_source = inspect.getsource(train.run)
    assert run_source.index("select(val_scores)") < run_source.index("evaluate_on_test(")
    assert run_source.index("choose_threshold(") < run_source.index("evaluate_on_test(")


# ---- Probabilities and determinism ----

def test_probabilities_are_valid_and_calibrated_on_average(df, result):
    _, validation, _ = split(df)
    probability = result.chosen_pipeline.predict_proba(model_input(validation))[:, 1]
    assert ((probability >= 0) & (probability <= 1)).all()
    assert abs(probability.mean() - validation[config.LABEL].mean()) < 0.01


def test_training_is_deterministic(df, result):
    train_rows, validation, _ = split(df)
    again = build(result.chosen).fit(model_input(train_rows), train_rows[config.LABEL])
    np.testing.assert_array_equal(again.predict_proba(model_input(validation)),
                                  result.chosen_pipeline.predict_proba(model_input(validation)))


def test_committed_report_is_up_to_date(result):
    # Fails if data, split, models or report changed without re-running `python -m ml.train`.
    assert train.REPORT.read_text() == train.build_report(result)
