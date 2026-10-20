"""Week 3: data, leakage and reproducibility of the training pipeline (no database needed)."""

import json
import subprocess
import sys
from pathlib import Path

import joblib
import numpy as np
import pytest

from ml import config, data, train
from ml.features import EXCLUDED_COLUMNS, INPUT_COLUMNS, build_preprocessor

COMMITTED = json.loads((config.ARTIFACT_DIR / f"{config.MODEL_NAME}-{config.MODEL_VERSION}.json").read_text())


@pytest.fixture(scope="module")
def small():
    return data.generate(n_rows=3000, n_patients=1000, seed=7)


class TestData:
    def test_generation_is_deterministic_per_seed(self, small):
        assert small.equals(data.generate(n_rows=3000, n_patients=1000, seed=7))
        assert not small.equals(data.generate(n_rows=3000, n_patients=1000, seed=8))

    def test_schema_ranges_and_missingness(self, small):
        assert small.no_show.isin([0, 1]).all()
        assert (small.prior_no_shows <= small.prior_appointments).all()
        assert small.appointment_hour.between(8, 18).all() and small.lead_time_days.between(0, 180).all()
        assert 0.05 < small.distance_km.isna().mean() < 0.15
        assert 0.10 < small.no_show.mean() < 0.25  # imbalanced, as documented

    def test_csv_never_contains_generator_internals(self, small, tmp_path):
        data.write(small, tmp_path / "d.csv")
        header = (tmp_path / "d.csv").read_text().splitlines()[0].split(",")
        assert data.TRUTH_COLUMN not in header


class TestLeakage:
    def test_excluded_columns_are_never_inputs(self):
        assert not set(EXCLUDED_COLUMNS) & set(INPUT_COLUMNS)
        assert "no_show" not in INPUT_COLUMNS

    def test_fitted_pipeline_sees_no_identifier_or_outcome_columns(self, small):
        prep = build_preprocessor(scale=True).fit(small[INPUT_COLUMNS])
        names = {n.removeprefix("missingindicator_") for n in prep.named_steps["columns"].get_feature_names_out()}
        # One-hot names look like "visit_type_video"; compare on the source column.
        sources = {n for n in names if n in INPUT_COLUMNS or not any(n.startswith(c + "_") for c in INPUT_COLUMNS)}
        assert not sources & {"checked_in", "patient_ref", "appointment_id", "no_show", data.TRUTH_COLUMN}

    def test_checked_in_would_be_a_perfect_leak(self, small):
        # Why it's excluded: it is the target, inverted.
        assert (small.checked_in == (small.no_show == 0)).all()

    def test_split_keeps_each_patient_in_one_split(self, small):
        tr, va, te = train.split(small, seed=1)
        assert len(tr) + len(va) + len(te) == len(small)
        sets = [set(s.patient_ref) for s in (tr, va, te)]
        assert not (sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])

    def test_shipped_imputer_was_fitted_on_the_training_split_only(self):
        # Rebuild the exact split used for the committed model and compare medians.
        full = data.generate()
        tr, va, te = train.split(full, config.SEED)
        model = joblib.load(config.ARTIFACT_DIR / COMMITTED["artifact_file"])
        imputer = model.named_steps["prep"].named_steps["columns"].named_transformers_["num"].named_steps["impute"]
        idx = list(imputer.feature_names_in_).index("distance_km")
        assert imputer.statistics_[idx] == pytest.approx(tr.distance_km.median())
        # Medians of 0.1-km values often coincide across splits, so also check a continuous statistic:
        # the scaler's mean must be the training-split mean, not the mean over all rows.
        scaler = model.named_steps["prep"].named_steps["columns"].named_transformers_["num"].named_steps["scale"]
        lead = list(imputer.feature_names_in_).index("lead_time_days")
        assert scaler.mean_[lead] == pytest.approx(tr.lead_time_days.mean())
        assert scaler.mean_[lead] != pytest.approx(full.lead_time_days.mean())


class TestReproducibility:
    def test_two_runs_produce_identical_artifacts_and_metrics(self, tmp_path):
        a = train.run(tmp_path / "a", tmp_path / "ra", n_rows=3000, data_path=tmp_path / "a" / "data.csv")
        b = train.run(tmp_path / "b", tmp_path / "rb", n_rows=3000, data_path=tmp_path / "b" / "data.csv")
        assert a["artifact_sha256"] == b["artifact_sha256"]
        assert a == b

    @pytest.mark.slow
    def test_full_training_run_reproduces_the_committed_model(self, tmp_path):
        # A fresh interpreter, like a reviewer running the script. (Inside this pytest process the
        # pickle bytes can differ after other models were trained here; predictions don't.)
        script = (
            "from pathlib import Path; from ml import train; import sys; "
            "t = Path(sys.argv[1]); train.run(t / 'art', t / 'rep', data_path=t / 'art' / 'data.csv')"
        )
        backend = Path(__file__).resolve().parent.parent
        subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=backend, check=True)
        rebuilt = json.loads((tmp_path / "art" / f"{config.MODEL_NAME}-{config.MODEL_VERSION}.json").read_text())
        assert rebuilt["data"]["sha256"] == COMMITTED["data"]["sha256"]
        assert rebuilt["test_metrics"] == COMMITTED["test_metrics"]
        assert rebuilt["artifact_sha256"] == COMMITTED["artifact_sha256"]


class TestCommittedModelQuality:
    def test_selected_model_beats_floor_and_raw_baseline_on_validation(self):
        val = COMMITTED["validation_metrics"]
        sel = COMMITTED["selected_model"]
        assert val[sel]["pr_auc"] > val["logistic_raw"]["pr_auc"] > val["majority_prior"]["pr_auc"]
        assert val[sel]["brier"] < val["majority_prior"]["brier"]

    def test_threshold_was_chosen_on_validation_and_is_a_probability(self):
        assert 0 < COMMITTED["decision_threshold"] < 1
        assert COMMITTED["decision_threshold"] > COMMITTED["train_no_show_rate"]  # bands stay ordered

    def test_environment_and_seed_are_recorded(self):
        env = COMMITTED["environment"]
        assert env["scikit_learn"] and env["numpy"] and env["pandas"]
        assert COMMITTED["seed"] == config.SEED
        assert np.isclose(sum(COMMITTED["data"]["split_rows"].values()), COMMITTED["data"]["rows"])
