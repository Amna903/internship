"""Step 6 evidence (acceptance check A1): the training script reproduces the released model, and the
loader refuses anything it should not open."""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import sklearn

from ml import artifact, config, inference, train
from ml.data import generate
from ml.models import RELEASE_CANDIDATES
from ml.preprocess import model_input
from ml.split import split

BACKEND = Path(__file__).resolve().parent.parent
MODEL, META = artifact.artifact_paths()


@pytest.fixture(scope="module")
def committed():
    return inference.load()


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory):
    """Rebuild the release in a brand-new Python process, into a temporary folder."""
    out = tmp_path_factory.mktemp("rebuilt")
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; from ml.artifact import build; build(Path(sys.argv[1]))",
            str(out),
        ],
        cwd=BACKEND,
        check=True,
        capture_output=True,
    )
    return out


@pytest.fixture
def copy(tmp_path):
    """A private copy of the released files that a test may damage."""
    for path in (MODEL, META):
        shutil.copy(path, tmp_path / path.name)
    return tmp_path


def sample_rows(n=300):
    return model_input(split(generate())[2]).head(n)


# ---- A1: the training script reproduces the model artifact ----


def test_rebuild_reproduces_data_metrics_and_predictions(rebuilt, committed):
    fresh = json.loads(artifact.artifact_paths(rebuilt)[1].read_text())
    assert fresh["training_data"] == committed.metadata["training_data"]  # level 1: identical data
    assert fresh["metrics"] == committed.metadata["metrics"]  # level 2: identical metrics
    assert fresh["decision"] == committed.metadata["decision"]
    rows = sample_rows()
    np.testing.assert_allclose(  # level 3: identical predictions
        inference.load(rebuilt).pipeline.predict_proba(rows), committed.pipeline.predict_proba(rows), rtol=0, atol=1e-9
    )


def test_rebuild_is_byte_identical_on_the_same_platform(rebuilt, committed):
    # Level 4. Pickled floats can differ in the last bits across CPUs/BLAS builds, so byte identity is
    # only promised on the platform that built the committed file (levels 1-3 are checked everywhere).
    built_on = committed.metadata["built_on"]
    fresh = json.loads(artifact.artifact_paths(rebuilt)[1].read_text())
    if fresh["built_on"] != built_on or fresh["libraries"] != committed.metadata["libraries"]:
        pytest.skip(f"committed file built on {built_on}; this run is {fresh['built_on']}")
    assert artifact.file_sha256(artifact.artifact_paths(rebuilt)[0]) == committed.metadata["artifact_sha256"]


def test_committed_model_equals_a_freshly_trained_one(committed):
    rows = sample_rows()
    fresh = train.run(candidates=RELEASE_CANDIDATES).chosen_pipeline
    np.testing.assert_allclose(committed.pipeline.predict_proba(rows), fresh.predict_proba(rows), rtol=0, atol=1e-9)


def test_metadata_matches_the_file_and_the_training_run(committed):
    assert committed.metadata["artifact_sha256"] == artifact.file_sha256(MODEL)
    result = train.run(candidates=RELEASE_CANDIDATES)
    assert committed.metadata["metrics"]["validation"]["pr_auc"] == round(result.validation[result.chosen].pr_auc, 6)
    assert committed.metadata["decision"]["threshold"] == round(result.threshold.value, 6)
    assert committed.metadata["estimator"] == result.chosen.label
    assert "created" not in json.dumps(committed.metadata)  # no timestamps: they would break reproducibility


def test_pinned_requirements_match_the_versions_the_model_was_built_with(committed):
    pins = dict(re.findall(r"^([a-z-]+)==([\d.]+)", (BACKEND / "requirements.txt").read_text(), re.M))
    for library in ("scikit-learn", "numpy", "pandas", "scipy", "joblib"):
        assert pins[library] == committed.metadata["libraries"][library], library


def test_committed_file_loads_in_a_fresh_process():
    code = (
        "from ml.inference import load; m = load(); "
        "print(m.version, round(float(m.pipeline.predict_proba(__import__('ml.preprocess', fromlist=['x'])"
        ".model_input(__import__('ml.data', fromlist=['x']).generate().head(1)))[0, 1]), 6))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=True)
    assert out.stdout.startswith(f"{config.MODEL_NAME}-{config.MODEL_VERSION} ")


# ---- The loader refuses what it should not open ----


def refuses(directory, reason_part, monkeypatch=None):
    if monkeypatch is not None:  # prove the file is never unpickled
        monkeypatch.setattr(inference.joblib, "load", lambda *a, **k: pytest.fail("unpickled a rejected file"))
    with pytest.raises(inference.ModelUnavailable) as exc:
        inference.load(directory)
    assert reason_part in exc.value.reason


def test_tampered_model_file_is_refused_without_being_unpickled(copy, monkeypatch):
    model = copy / MODEL.name
    data = bytearray(model.read_bytes())
    data[len(data) // 2] ^= 0xFF  # flip one byte
    model.write_bytes(bytes(data))
    refuses(copy, "SHA-256", monkeypatch)


def test_wrong_scikit_learn_version_is_refused(copy, monkeypatch):
    meta = json.loads((copy / META.name).read_text())
    meta["libraries"]["scikit-learn"] = "0.24.2"
    (copy / META.name).write_text(json.dumps(meta))
    refuses(copy, f"running {sklearn.__version__}", monkeypatch)


def test_schema_mismatch_is_refused(copy, monkeypatch):
    meta = json.loads((copy / META.name).read_text())
    del meta["features"]["distance_km"]
    (copy / META.name).write_text(json.dumps(meta))
    refuses(copy, "feature schema", monkeypatch)


def test_wrong_version_in_metadata_is_refused(copy, monkeypatch):
    meta = json.loads((copy / META.name).read_text())
    meta["version"] = "9.9.9"
    (copy / META.name).write_text(json.dumps(meta))
    refuses(copy, "expected", monkeypatch)


@pytest.mark.parametrize("which", ["model", "metadata"])
def test_missing_file_is_refused(copy, which, monkeypatch):
    (copy / (MODEL.name if which == "model" else META.name)).unlink()
    refuses(copy, "missing file", monkeypatch)


def test_unreadable_metadata_is_refused(copy, monkeypatch):
    (copy / META.name).write_text("{not json")
    refuses(copy, "unreadable", monkeypatch)


# ---- Output wording and decision rule ----


def test_suggestion_at_the_boundaries():
    assert inference.suggested_action(0.20, 0.20) == "extra_reminder_suggested"  # exactly at the threshold
    assert inference.suggested_action(0.1999, 0.20) == "standard_reminder"


def test_output_uses_plain_non_clinical_wording(committed):
    out = committed.predict(sample_rows(50).to_dict("records"))
    text = json.dumps(out).lower() + json.dumps(config.ACTIONS).lower()
    for word in ("risk", "high", "diagnos", "disease", "illness", "patient is", "clinical"):
        assert word not in text, word
    assert {o["suggested_action"] for o in out} <= set(config.ACTIONS)
    assert "not a medical assessment" in config.DISCLAIMER.lower()


def test_predictions_are_valid_probabilities_with_the_version(committed):
    out = committed.predict(sample_rows(200).to_dict("records"))
    assert all(0 <= o["no_show_probability"] <= 1 for o in out)
    assert committed.version == f"{config.MODEL_NAME}-{config.MODEL_VERSION}"


def test_verify_release_reports_exactly_which_metadata_sections_differ(committed):
    from ml.verify_release import compare_metadata

    same = json.loads(json.dumps(committed.metadata))
    assert compare_metadata(committed.metadata, same) == []
    changed = {**same, "decision": {**same["decision"], "threshold": 0.5}, "seed": 7}
    assert compare_metadata(committed.metadata, changed) == ["seed", "decision"]
    # platform and file hash may legitimately differ between machines, so they are not compared here
    assert (
        compare_metadata(committed.metadata, {**same, "built_on": {"platform": "linux"}, "artifact_sha256": "x"}) == []
    )
