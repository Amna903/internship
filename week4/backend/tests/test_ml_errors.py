"""Step 5 evidence: error-analysis numbers are correct, the calibration rule accounts for sampling noise,
findings are reported rather than forced, nothing reads test labels, and the shipped model is unchanged."""

import pandas as pd
import pytest

from ml import config, errors, train
from ml.data import generate
from ml.split import split


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def analysis(df):
    return errors.analyse(df)


# ---- Hand-checked building blocks ----

def test_confusion_and_rates_on_a_tiny_example():
    y = [1, 1, 1, 0, 0, 0, 0, 0]
    flagged = [1, 1, 0, 1, 0, 0, 0, 0]
    c = errors.confusion(y, flagged)
    assert c == {"tp": 2, "fp": 1, "fn": 1, "tn": 4}
    r = errors.rates(c)
    assert r["fpr"] == pytest.approx(1 / 5) and r["recall"] == pytest.approx(2 / 3)
    assert r["precision"] == pytest.approx(2 / 3) and r["flag_rate"] == pytest.approx(3 / 8)


def test_expected_calibration_error_by_hand():
    table = pd.DataFrame({"n": [100, 300], "gap": [0.04, -0.02]})
    assert errors.expected_calibration_error(table) == pytest.approx((100 * 0.04 + 300 * 0.02) / 400)


def test_noise_limit_is_the_bonferroni_value_for_ten_bins():
    # two-sided 5% spread over 10 bins -> 0.5% per bin -> |z| > 2.807
    assert errors.CALIBRATION_Z_LIMIT == pytest.approx(2.807, abs=0.001)


def test_fairness_gaps_by_hand():
    table = pd.DataFrame({"fpr": [0.6, 0.2], "recall": [0.9, 0.5], "flag_rate": [0.8, 0.2]}, index=["young", "old"])
    gaps = errors.fairness_gaps(table, "young", "old")
    assert gaps["fpr_gap"] == pytest.approx(0.4) and gaps["recall_gap"] == pytest.approx(0.4)
    assert gaps["flag_rate_ratio"] == pytest.approx(4.0)


def test_error_sources_by_hand():
    y = [1, 1, 0, 0]
    flagged = [0, 0, 1, 1]  # two FN, two FP
    truth = [0.05, 0.50, 0.50, 0.05]  # threshold 0.2: oracle flags rows 2 and 3
    assert errors.error_sources(y, flagged, truth, 0.2) == {"fn": 2, "fn_unavoidable": 1, "fp": 2, "fp_unavoidable": 1}


# ---- Calibration rule: noise-aware, and never changes the shipped model ----

def test_a_gap_within_sampling_noise_is_not_flagged():
    # 400 rows predicted at 15%: se = 1.8 pts, so a 3-point gap (z = 1.7) is noise, not miscalibration.
    y = [1] * 72 + [0] * 328  # observed 18%
    table = errors.calibration_table(y, [0.15] * 400, bins=1)
    assert not table["flagged"].any()


def test_a_large_gap_is_flagged_and_reported_as_a_finding_not_applied():
    y = [1] * 120 + [0] * 280  # observed 30% vs predicted 15%: z ~ 8
    table = errors.calibration_table(y, [0.15] * 400, bins=1)
    assert table["flagged"].all()
    verdict = errors.calibration_verdict(table)
    assert "Finding" in verdict and "NOT applied" in verdict


def test_shipped_model_and_threshold_are_the_step_4_ones(df, analysis):
    result = train.run(df)
    assert analysis.model_label == result.chosen.label
    assert analysis.threshold == result.threshold.value


# ---- Real numbers are consistent ----

def test_confusion_adds_up_to_the_validation_rows(df, analysis):
    assert sum(analysis.val_confusion.values()) == analysis.validation_rows == len(split(df)[1])


def test_every_group_table_covers_every_validation_row_once(analysis):
    for name, table in analysis.groups.items():
        assert table["rows"].sum() == analysis.validation_rows, name


def test_calibration_bins_cover_every_row(analysis):
    assert analysis.calibration["n"].sum() == analysis.validation_rows
    assert len(analysis.calibration) == errors.CALIBRATION_BINS


# ---- Findings are reported, not forced ----

def test_report_states_each_direction_result_truthfully(analysis):
    report = errors.build_report(analysis)
    for d in analysis.directions:
        row = next(line for line in report.splitlines() if line.startswith(f"| {d['effect']} |"))
        assert ("✅ matches" in row) == d["matches"]


def test_report_states_the_calibration_verdict_that_the_numbers_give(analysis):
    assert errors.calibration_verdict(analysis.calibration) in errors.build_report(analysis)


# ---- No decision reads test labels ----

def test_analysis_does_not_depend_on_test_labels(df, analysis):
    _, _, test = split(df)
    scrambled = df.copy()
    scrambled.loc[test.index, config.LABEL] = ~scrambled.loc[test.index, config.LABEL]
    again = errors.analyse(scrambled)
    pd.testing.assert_frame_equal(again.calibration, analysis.calibration)
    assert again.val_confusion == analysis.val_confusion
    assert again.without_age == analysis.without_age
    assert again.directions == analysis.directions
    assert again.test_confusion != analysis.test_confusion  # the reporting-only part does see test rows


def test_committed_report_is_up_to_date(analysis):
    assert errors.REPORT.read_text() == errors.build_report(analysis)
