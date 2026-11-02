"""Step 3 evidence: the split keeps patients whole, engineered features are safe at their edge cases,
and every learned preprocessing value comes from the training split only."""

import copy

import numpy as np
import pandas as pd
import pytest

from ml import config
from ml.data import generate
from ml.features import ENGINEERED_NUMERIC, engineer
from ml.preprocess import build_preprocessor, model_input
from ml.split import split


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def parts(df):
    return split(df)


def row(**overrides):
    """One valid feature row, with chosen values overridden."""
    base = {
        "lead_time_days": 10,
        "appointment_weekday": "tuesday",
        "appointment_hour": 10,
        "age_band": "35-44",
        "visit_type": "in_person",
        "booking_channel": "web",
        "reminder_sent": True,
        "prior_appointments": 4,
        "prior_no_shows": 2,
        "distance_km": 5.0,
    }
    return pd.DataFrame([{**base, **overrides}])[config.FEATURES]


# ---------------- A. Split ----------------


def test_no_patient_appears_in_two_parts(parts):
    train, validation, test = (set(p["patient_id"]) for p in parts)
    assert not (train & validation) and not (train & test) and not (validation & test)


def test_every_row_lands_in_exactly_one_part(df, parts):
    ids = pd.concat([p["appointment_id"] for p in parts])
    assert ids.is_unique and set(ids) == set(df["appointment_id"])


def test_split_is_reproducible(df, parts):
    for again, before in zip(split(df), parts):
        assert again["appointment_id"].tolist() == before["appointment_id"].tolist()


def test_parts_are_roughly_60_20_20_and_representative(df, parts):
    overall = df[config.LABEL].mean()
    for part, share in zip(parts, (0.6, 0.2, 0.2)):
        assert abs(len(part) / len(df) - share) < 0.02
        assert abs(part[config.LABEL].mean() - overall) < 0.02


# ---------------- B. Engineered features: edge cases ----------------


def test_same_day_appointment_gives_log_lead_time_zero_not_minus_infinity():
    out = engineer(row(lead_time_days=0))
    assert out["log_lead_time"].iloc[0] == 0.0
    assert np.isfinite(out[ENGINEERED_NUMERIC].to_numpy()).all()


def test_first_appointment_without_history_does_not_divide_by_zero():
    out = engineer(row(prior_appointments=0, prior_no_shows=0))
    assert out["prior_no_show_rate"].iloc[0] == 0.0
    assert out["has_history"].iloc[0] == 0.0
    assert np.isfinite(out[ENGINEERED_NUMERIC].to_numpy()).all()


def test_new_patient_and_never_missed_are_distinguishable():
    new, reliable = (
        engineer(row(prior_appointments=0, prior_no_shows=0)),
        engineer(row(prior_appointments=5, prior_no_shows=0)),
    )
    assert new["prior_no_show_rate"].iloc[0] == reliable["prior_no_show_rate"].iloc[0] == 0.0
    assert new["has_history"].iloc[0] != reliable["has_history"].iloc[0]


def test_normal_values():
    out = engineer(row(lead_time_days=60, prior_appointments=4, prior_no_shows=2, reminder_sent=True))
    assert out["prior_no_show_rate"].iloc[0] == 0.5
    assert out["log_lead_time"].iloc[0] == pytest.approx(np.log(61))
    assert out["reminder_x_lead"].iloc[0] == 1.0  # capped at 30 days
    assert engineer(row(reminder_sent=False))["reminder_x_lead"].iloc[0] == 0.0


def test_no_nan_or_infinity_anywhere_in_the_dataset(df):
    assert np.isfinite(engineer(model_input(df))[ENGINEERED_NUMERIC].to_numpy()).all()


def test_engineering_learns_nothing_from_data(parts):
    # Stateless: the same row gets the same features whatever data came before it.
    one = row(lead_time_days=5)
    assert engineer(one).equals(
        engineer(pd.concat([model_input(parts[0]).head(50), one]).tail(1).reset_index(drop=True))
    )


# ---------------- C/D. Pipeline: learns from training data only ----------------


@pytest.fixture(scope="module", params=[False, True], ids=["raw", "engineered"])
def fitted(request, parts):
    return build_preprocessor(engineered=request.param).fit(model_input(parts[0])), request.param


def numeric_step(pipeline):
    return pipeline.named_steps["columns"].named_transformers_["numeric"]


def test_imputation_median_comes_from_training_split_only(fitted, df, parts):
    pipeline, _ = fitted
    learned = dict(
        zip(numeric_step(pipeline).feature_names_in_, numeric_step(pipeline).named_steps["impute"].statistics_)
    )
    train_median = parts[0]["distance_km"].median()
    assert learned["distance_km"] == train_median
    assert train_median != df["distance_km"].median()  # so the check really tells the two apart


def test_scaler_statistics_come_from_training_split_only(fitted, parts):
    pipeline, _ = fitted
    names = list(numeric_step(pipeline).feature_names_in_)
    mean = numeric_step(pipeline).named_steps["scale"].mean_[names.index("lead_time_days")]
    assert mean == pytest.approx(parts[0]["lead_time_days"].mean())


def test_transforming_validation_and_test_never_refits(fitted, parts):
    pipeline, _ = fitted
    before = copy.deepcopy(numeric_step(pipeline).named_steps["scale"].__dict__)
    pipeline.transform(model_input(parts[1]))
    pipeline.transform(model_input(parts[2]))
    after = numeric_step(pipeline).named_steps["scale"].__dict__
    assert all(
        np.array_equal(before[k], after[k]) if isinstance(before[k], np.ndarray) else before[k] == after[k]
        for k in before
    )


def test_output_has_no_missing_values_and_a_missing_flag(fitted, parts):
    pipeline, engineered = fitted
    X = pipeline.transform(model_input(parts[2]))
    assert np.isfinite(X).all()
    names = list(pipeline.get_feature_names_out())
    assert "missingindicator_distance_km" in names
    assert all(f in names for f in ENGINEERED_NUMERIC) == engineered


@pytest.mark.parametrize("forbidden", ["patient_id", "appointment_id", config.LABEL, config.ORACLE])
def test_forbidden_columns_are_rejected(parts, forbidden):
    with pytest.raises(ValueError, match="Not allowed"):
        build_preprocessor(engineered=True).fit(parts[0][config.FEATURES + [forbidden]])


def test_missing_feature_is_rejected_not_silently_dropped(parts):
    with pytest.raises(ValueError, match="missing"):
        build_preprocessor(engineered=True).fit(parts[0][config.FEATURES[1:]])


def test_unseen_category_at_prediction_time_does_not_crash(fitted):
    pipeline, _ = fitted
    assert np.isfinite(pipeline.transform(row(booking_channel="carrier_pigeon"))).all()


# ---------------- Save / reload (custom transformers must survive joblib) ----------------


def test_fitted_pipeline_survives_joblib_save_and_reload_in_a_fresh_process(fitted, parts, tmp_path):
    """ColumnGuard, EngineeredFeatures and _as_float are our own code. Loading a joblib file needs them
    importable under the same module path, so this reloads in a separate Python process (a fresh
    interpreter has none of this test's objects in memory) and compares the output exactly."""
    import json
    import subprocess
    import sys
    from pathlib import Path

    import joblib

    pipeline, _ = fitted
    path, rows = tmp_path / "pipeline.joblib", tmp_path / "rows.csv"
    joblib.dump(pipeline, path)
    model_input(parts[2]).head(200).to_csv(rows, index=False)
    code = (
        "import joblib, json, sys, pandas as pd; "
        "p = joblib.load(sys.argv[1]); X = pd.read_csv(sys.argv[2]); "
        "print(json.dumps(p.transform(X).tolist()))"
    )
    backend = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-c", code, str(path), str(rows)], cwd=backend, capture_output=True, text=True, check=True
    )
    reloaded = np.array(json.loads(result.stdout))
    np.testing.assert_allclose(reloaded, pipeline.transform(pd.read_csv(rows)), rtol=0, atol=1e-12)
