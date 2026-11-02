"""Step 2 evidence: the EDA report is deterministic, its numbers match the data, and its leakage check works."""

import pytest

from ml import config
from ml.data import dataset_hash, generate
from ml.eda import LEAKAGE_AUC, REPORT, build_report, single_feature_auc, two_proportion_p_value


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def report(df):
    return build_report(df)


def test_report_is_deterministic(df, report):
    assert build_report(generate()) == report


def test_committed_report_is_up_to_date(report):
    # Fails if the generator or EDA changed without re-running `python -m ml.eda`.
    assert REPORT.read_text() == report


def test_report_states_the_real_numbers(df, report):
    assert f"{len(df):,}" in report
    assert dataset_hash(df) in report
    assert f"{100 * df[config.LABEL].mean():.1f}% no-shows" in report
    assert f"{int(df['distance_km'].isna().sum()):,}" in report


def test_report_covers_every_required_section(report):
    for heading in [
        "Class balance",
        "Missing values",
        "Numeric features",
        "Categorical features",
        "Each feature against the no-show rate",
        "Relationships between numeric features",
        "Leakage and split readiness",
        "Bias: age",
        "Decisions this analysis supports",
    ]:
        assert heading in report


def test_no_real_feature_looks_like_leakage(df):
    assert max(single_feature_auc(df).values()) < LEAKAGE_AUC


def test_leakage_check_catches_a_column_that_encodes_the_answer(df, monkeypatch):
    leaky = df.assign(checked_in=~df[config.LABEL])  # only known after the appointment
    monkeypatch.setattr(config, "FEATURES", config.FEATURES + ["checked_in"])
    monkeypatch.setattr(config, "BOOLEAN_FEATURES", config.BOOLEAN_FEATURES + ["checked_in"])
    assert single_feature_auc(leaky)["checked_in"] > LEAKAGE_AUC


def test_ids_and_oracle_are_not_scored_as_features(df):
    scored = set(single_feature_auc(df))
    assert scored == set(config.FEATURES)


def test_p_value_helper():
    assert two_proportion_p_value(50, 100, 50, 100) == pytest.approx(1.0)
    assert two_proportion_p_value(80, 100, 20, 100) < 1e-6
