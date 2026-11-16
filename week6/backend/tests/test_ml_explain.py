"""Week 4 Step 5 evidence (S11, S12): permutation importance is seeded and behaves on planted features,
grouped shuffling counts shared credit once, the FP/FN profiles add up, every sentence's direction is
computed from the numbers, and the test set is never used."""

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from ml import config, explain
from ml.data import generate
from ml.split import split
from ml.verify_release import reports_match


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def analysis(df):
    return explain.analyse(df)


@pytest.fixture(scope="module")
def toy():
    """A planted problem: `signal` drives the label, `noise` does nothing."""
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"signal": rng.normal(size=4000), "noise": rng.normal(size=4000)})
    y = (X["signal"] + rng.normal(scale=0.5, size=4000)) > 0
    return X, y


# ---- Permutation importance on planted features ----


def test_a_useless_feature_gets_about_zero_and_a_real_one_dominates(toy):
    X, y = toy
    imp = explain.importances(LogisticRegression().fit(X, y), X, y, repeats=5)
    assert explain.within_noise(imp["noise"])
    assert imp["signal"]["mean"] > 0.2 and not explain.within_noise(imp["signal"])


def test_a_perfect_feature_dominates_everything(toy):
    X, y = toy
    X = X.assign(answer=y.astype(float))
    imp = explain.importances(LogisticRegression().fit(X, y), X, y, repeats=5)
    assert max(imp, key=lambda f: imp[f]["mean"]) == "answer"


def test_importances_are_seeded_and_reproducible(toy):
    X, y = toy
    model = LogisticRegression().fit(X, y)
    assert explain.importances(model, X, y, repeats=5) == explain.importances(model, X, y, repeats=5)


# ---- Grouped shuffling ----


def test_group_shuffle_reveals_credit_that_two_copies_hide_from_each_other(toy):
    """Two copies of the same signal cover for each other: shuffling one alone barely hurts, shuffling
    both together removes the signal. This is the 'understate' case of the caveat."""
    X, y = toy
    X = X.assign(copy=X["signal"])
    model = LogisticRegression().fit(X, y)
    single = explain.importances(model, X, y, repeats=5)
    group = explain.group_importance(model, X, y, ["signal", "copy"], repeats=5)
    assert group["mean"] > single["signal"]["mean"] + single["copy"]["mean"]


def test_history_group_is_reported_with_the_sum_of_its_singles(analysis):
    g = analysis["groups"]["history (prior_appointments + prior_no_shows)"]
    assert g["sum_of_singles"] == pytest.approx(
        analysis["single"]["prior_appointments"]["mean"] + analysis["single"]["prior_no_shows"]["mean"]
    )


def test_report_reading_of_the_group_matches_the_numbers(analysis):
    g = analysis["groups"]["history (prior_appointments + prior_no_shows)"]
    reading = explain._group_reading(analysis)
    assert ("**overstate**" in reading) == (g["mean"] <= g["sum_of_singles"])
    assert ("understated" in reading) == (g["mean"] > g["sum_of_singles"])


def test_shuffling_prior_no_shows_alone_creates_rows_that_cannot_exist(df):
    validation = split(df)[1]
    assert (validation["prior_no_shows"] > validation["prior_appointments"]).sum() == 0
    assert 0 < explain.impossible_share(validation, repeats=3) < 0.1


# ---- Random forest importance ----


def test_impurity_importance_sums_to_one_across_inputs_and_engineered_features(analysis):
    assert sum(analysis["forest_impurity"].values()) == pytest.approx(1.0)


@pytest.mark.parametrize(
    "encoded, source",
    [
        ("age_band_18-24", "age_band"),
        ("missingindicator_distance_km", "distance_km"),
        ("booking_channel_web", "booking_channel"),
        ("log_lead_time", "log_lead_time"),
        ("lead_time_days", "lead_time_days"),
    ],
)
def test_model_columns_map_to_their_input(encoded, source):
    assert explain.source_of(encoded) == source


# ---- False positives and negatives ----


def test_profiles_add_up_to_the_validation_rows_and_match_the_error_counts(analysis):
    p = analysis["profiles"]
    parts = [
        "true positives",
        "false positives (attended, flagged)",
        "false negatives (missed, not flagged)",
        "true negatives",
    ]
    assert sum(p[k]["rows"] for k in parts) == p["all validation"]["rows"] == analysis["validation_rows"]
    assert p["false positives (attended, flagged)"]["rows"] == analysis["sources"]["fp"]
    assert p["false negatives (missed, not flagged)"]["rows"] == analysis["sources"]["fn"]


def test_every_direction_in_the_fp_fn_sentences_is_computed(analysis):
    everyone = analysis["profiles"]["all validation"]
    for kind in ["false positives (attended, flagged)", "false negatives (missed, not flagged)"]:
        group = analysis["profiles"][kind]
        sentence = explain._compare(group, everyone)
        assert ("more often reminded" in sentence) == (group["reminder"] > everyone["reminder"])
        assert ("more often aged 18–24" in sentence) == (group["young"] > everyone["young"])


# ---- Rules ----


def test_explanation_never_uses_the_test_set(df, analysis):
    _, _, test = split(df)
    flipped = df.copy()
    flipped.loc[test.index, config.LABEL] = ~flipped.loc[test.index, config.LABEL]
    assert explain.build_report(explain.analyse(flipped)) == explain.build_report(analysis)


def test_planted_strongest_inputs_rank_near_the_top(analysis):
    ranked = sorted(analysis["single"], key=lambda f: -analysis["single"][f]["mean"])
    assert set(explain.PLANTED_STRONGEST) <= set(ranked[:4])


def test_committed_report_is_up_to_date(analysis):
    ok, reason = reports_match(explain.REPORT.read_text(), explain.build_report(analysis))
    assert ok, reason
