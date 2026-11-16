"""Guards the fresh holdout reserved for the next final evaluation (mentor review on PR #1): a different
seed, IDs that cannot collide with the main dataset, a pinned fingerprint, and no code that could use it
for exploration, tuning, model choice or release selection. Nothing here looks at its outcomes."""

import re
from pathlib import Path

import pytest

from ml import config, holdout
from ml.data import generate

BACKEND = Path(__file__).resolve().parents[1]
# Code that could load the holdout: importing the module, or calling its loader. Mentioning the word in a
# docstring or report text is fine (train.py and release_rule.py explain that it is reserved).
LOADS_HOLDOUT = re.compile(r"load_holdout|\bholdout\s+import|^\s*(from|import)\s[^\n]*\bholdout\b", re.M)


@pytest.fixture(scope="module")
def reserved():
    return holdout.load_holdout()


def test_holdout_uses_a_different_seed():
    assert holdout.HOLDOUT_SEED != config.SEED


def test_no_patient_or_appointment_id_can_collide_with_the_main_dataset(reserved):
    main = generate()
    assert not set(reserved["patient_id"]) & set(main["patient_id"])
    assert not set(reserved["appointment_id"]) & set(main["appointment_id"])
    assert reserved["patient_id"].min() > holdout.ID_OFFSET > main["appointment_id"].max()


def test_holdout_is_exactly_the_reserved_data(reserved):
    """Pinned fingerprint: a changed generator, seed or size fails here instead of silently drifting."""
    from ml.data import dataset_hash
    assert dataset_hash(reserved) == holdout.HOLDOUT_SHA256
    assert reserved["patient_id"].nunique() == holdout.N_PATIENTS


def test_only_the_holdout_module_may_load_it():
    """No module in ml/ or the API references the holdout, so no tuning, choice or release code can use
    it. The next final evaluation will be added here explicitly, as the one allowed user."""
    allowed = {BACKEND / "ml" / "holdout.py"}
    offenders = []
    for folder in ["ml", "predictions", "config", "audit", "profiles", "accounts"]:
        for path in (BACKEND / folder).rglob("*.py"):
            if path not in allowed and LOADS_HOLDOUT.search(path.read_text()):
                offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == []


@pytest.mark.parametrize("source, loads", [("from . import holdout", True), ("from .holdout import load_holdout", True),
                                           ("import ml.holdout", True), ("df = load_holdout()", True),
                                           ('"""the holdout is reserved"""', False)])
def test_the_guard_catches_imports_and_calls_but_not_mentions(source, loads):
    assert bool(LOADS_HOLDOUT.search(source)) is loads


def test_holdout_is_not_written_to_the_repository():
    """It is regenerated from its seed when needed; no copy of its rows is committed."""
    committed = [p for p in BACKEND.rglob("*holdout*") if p.suffix in {".csv", ".parquet", ".joblib", ".json"}]
    assert committed == []
