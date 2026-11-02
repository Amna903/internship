"""Week 4 Step 6 evidence (U1, U4): one row per patient of non-sensitive engagement features, exclusions
enforced, the scaling rule applied as written, and the report stating what the generator implies."""

import numpy as np
import pandas as pd
import pytest

from ml import cluster_features as cf
from ml import config
from ml.data import generate


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def table(df):
    return cf.patient_table(df)


# ---- One row per patient ----

def test_one_row_per_patient_in_feature_order(df, table):
    assert len(table) == df["patient_id"].nunique() and table.index.is_unique
    assert list(table.columns) == list(cf.FEATURES)


def test_values_for_a_hand_made_patient():
    rows = pd.DataFrame({
        "patient_id": [7, 7, 7, 7],
        "lead_time_days": [2, 4, 10, 20],
        "visit_type": ["telehealth", "in_person", "in_person", "telehealth"],
        "booking_channel": ["phone", "app", "web", "phone"],
        "appointment_hour": [8, 10, 14, 16],
    })
    row = cf.patient_table(rows).loc[7]
    assert row["mean_lead_time"] == 9.0
    assert row["telehealth_share"] == 0.5
    assert row["phone_share"] == 0.5 and row["app_share"] == 0.25
    assert row["mean_hour"] == 12.0 and row["appointments"] == 4


def test_table_is_deterministic(df, table):
    pd.testing.assert_frame_equal(cf.patient_table(generate()), table)


# ---- Exclusions ----

@pytest.mark.parametrize("excluded", ["age_band", "distance_km", "prior_appointments", "prior_no_shows", "no_show",
                                      config.ORACLE, "reminder_sent", "web_share", "appointment_weekday"])
def test_excluded_columns_never_become_features(table, excluded):
    assert excluded in cf.EXCLUDED
    assert excluded not in table.columns and not any(excluded in c for c in table.columns)


def test_no_feature_is_built_from_an_excluded_column():
    import inspect
    source = inspect.getsource(cf.patient_table)
    for column in ["age_band", "distance_km", "prior_no_shows", "no_show", "reminder_sent", config.ORACLE]:
        assert f'"{column}"' not in source


def test_web_share_is_left_out_because_the_three_shares_sum_to_one(df):
    g = df.groupby("patient_id")["booking_channel"]
    web = g.agg(lambda s: (s == "web").mean())
    table = cf.patient_table(df)
    np.testing.assert_allclose(web, 1 - table["phone_share"] - table["app_share"], atol=1e-12)


# ---- Scaling rule ----

def test_rule_picks_robust_scaling_for_these_patients(table):
    name, reason = cf.choose_scaler(cf.scaling_facts(table))
    assert name == "robust" and "mean_lead_time" in reason


@pytest.mark.parametrize("facts, expected", [
    ({"a": {"max_abs_z": 3.0, "iqr": 1.0, "skew": 0}, "b": {"max_abs_z": 2.0, "iqr": 1.0, "skew": 0}}, "standard"),
    ({"a": {"max_abs_z": 7.0, "iqr": 1.0, "skew": 0}, "b": {"max_abs_z": 2.0, "iqr": 1.0, "skew": 0}}, "robust"),
    ({"a": {"max_abs_z": 7.0, "iqr": 1.0, "skew": 0}, "b": {"max_abs_z": 2.0, "iqr": 0.0, "skew": 0}}, "standard"),
])
def test_scaling_rule_cases(facts, expected):
    assert cf.choose_scaler(facts)[0] == expected


def test_scaled_matrix_uses_the_chosen_scaler(table):
    matrix, name, _ = cf.scaled(table)
    assert matrix.shape == table.shape
    np.testing.assert_allclose(np.median(matrix, axis=0), 0, atol=1e-12)  # RobustScaler centres on the median


# ---- Report ----

def test_report_states_how_the_data_was_generated_and_what_to_expect(df):
    report = cf.build_report(df)
    assert "drawn **independently for every appointment" in report
    assert "**Weak or no cluster structure is" in report
    assert "reflects what the clinic does, not how the patient engages" in report


def test_report_counts_single_appointment_patients(df, table):
    single = int((table["appointments"] == 1).sum())
    assert f"{single:,} patients" in cf.build_report(df)


def test_committed_report_is_up_to_date(df):
    assert cf.REPORT.read_text() == cf.build_report(df)
