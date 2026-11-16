"""Step 1 evidence: the synthetic dataset is reproducible, valid, leak-free and has the planted properties.

Pure Python tests (no database). The dataset is generated once per module because it takes ~1 s.
"""

import numpy as np
import pytest

from ml import config
from ml.data import dataset_hash, generate


@pytest.fixture(scope="module")
def df():
    return generate()


# ---- Reproducibility (feeds acceptance check A1: training must reproduce the model) ----


def test_same_seed_gives_identical_data(df):
    assert dataset_hash(generate()) == dataset_hash(df)


def test_different_seed_gives_different_data(df):
    assert dataset_hash(generate(seed=7)) != dataset_hash(df)


# ---- Schema and value ranges ----


def test_schema_is_exactly_ids_features_oracle_and_label(df):
    assert set(df.columns) == set(config.ID_COLUMNS + config.FEATURES + [config.ORACLE, config.LABEL])


def test_values_stay_in_their_allowed_ranges(df):
    assert df["lead_time_days"].between(0, config.LEAD_TIME_MAX_DAYS).all()
    assert df["appointment_hour"].between(*config.HOUR_RANGE).all()
    assert (df["distance_km"].dropna() >= 0).all()
    assert df["appointment_weekday"].isin(config.WEEKDAYS).all()
    assert df["age_band"].isin(config.AGE_BANDS).all()
    assert df["visit_type"].isin(config.VISIT_TYPES).all()
    assert df["booking_channel"].isin(config.BOOKING_CHANNELS).all()
    assert df[config.ORACLE].between(0, 1).all()


def test_no_shows_never_exceed_appointments(df):
    assert (df["prior_no_shows"] <= df["prior_appointments"]).all()


def test_ids_are_unique_and_patients_have_several_appointments(df):
    assert df["appointment_id"].is_unique
    assert df["patient_id"].nunique() == config.N_PATIENTS
    assert df.groupby("patient_id").size().mean() > 3  # why the split must be grouped by patient


def test_history_grows_in_time_order_within_a_patient(df):
    for _, group in df.groupby("patient_id").head(1000).groupby("patient_id"):
        assert group["prior_appointments"].is_monotonic_increasing
        assert group["prior_no_shows"].is_monotonic_increasing


# ---- Planted properties the brief asks us to handle and document ----


def test_class_imbalance_is_in_the_documented_band(df):
    assert 0.14 <= df[config.LABEL].mean() <= 0.19  # minority class: accuracy would mislead


def test_missing_values_exist_only_where_planted(df):
    assert abs(df["distance_km"].isna().mean() - config.MISSING_DISTANCE_RATE) < 0.01
    assert df.drop(columns=["distance_km"]).notna().all().all()


def test_age_bias_is_present(df):
    rates = df.groupby("age_band")[config.LABEL].mean()
    assert rates["18-24"] > 1.5 * rates["55-64"]


def test_reminder_helps_more_for_appointments_booked_far_ahead(df):
    def reminder_gain(rows):
        return rows[~rows["reminder_sent"]][config.LABEL].mean() - rows[rows["reminder_sent"]][config.LABEL].mean()

    assert reminder_gain(df[df["lead_time_days"] >= 30]) > 3 * reminder_gain(df[df["lead_time_days"] <= 2])


def test_true_probability_is_calibrated_against_the_labels(df):
    # Sanity check of the generator itself: rows with ~20% true probability miss ~20% of the time.
    bins = np.digitize(df[config.ORACLE], [0.1, 0.2, 0.3])
    for b in range(4):
        group = df[bins == b]
        assert abs(group[config.LABEL].mean() - group[config.ORACLE].mean()) < 0.02


# ---- Leakage guards ----


def test_ids_label_and_oracle_are_never_features():
    forbidden = set(config.ID_COLUMNS) | {config.LABEL, config.ORACLE}
    assert forbidden.isdisjoint(config.FEATURES)


def test_hidden_reliability_is_not_written_to_the_dataset(df):
    assert not any("reliab" in column for column in df.columns)
