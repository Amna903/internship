"""Week 4 Step 3 evidence (S9, S10, C1, A3): stratified patient-grouped folds on training rows only, a
seeded RandomizedSearchCV, the one-standard-error rule, and a committed result the report agrees with.

The full 30-draw search takes minutes, so it runs in `python -m ml.verify_release` (its own CI job).
Here the logic is tested on tiny searches, and the committed result is checked for consistency."""

import json

import numpy as np
import pytest

from ml import config, train, tune
from ml.data import generate
from ml.models import CANDIDATES, GRID_CANDIDATES
from ml.split import split
from ml.verify_release import reports_match


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def parts(df):
    return split(df)


@pytest.fixture(scope="module")
def folds(parts):
    return tune.make_folds(parts[0])


@pytest.fixture(scope="module")
def committed():
    return json.loads(tune.RESULT.read_text())


# ---- Folds ----

def test_folds_cover_every_training_row_exactly_once_as_scoring_rows(parts, folds):
    scored = np.concatenate([s for _, s in folds])
    assert len(folds) == tune.N_SPLITS
    assert sorted(scored) == list(range(len(parts[0])))


def test_no_patient_is_in_two_folds(parts, folds):
    train_rows = parts[0]
    patients = [set(train_rows.iloc[s]["patient_id"]) for _, s in folds]
    for i in range(len(patients)):
        for j in range(i + 1, len(patients)):
            assert not patients[i] & patients[j]


def test_folds_are_stratified(parts, folds):
    rates = [parts[0].iloc[s][config.LABEL].mean() for _, s in folds]
    assert max(rates) - min(rates) < 0.01


def test_tuning_only_ever_sees_training_rows(df, parts, monkeypatch):
    """Every row handed to the folds, the cross-validation and the search must come from the train
    part; none from validation or test."""
    seen = []
    real_make_folds = tune.make_folds
    monkeypatch.setattr(tune, "make_folds", lambda rows, n: seen.append(set(rows.index)) or real_make_folds(rows, n))
    monkeypatch.setattr(tune, "cross_validate", lambda c, rows, f: seen.append(set(rows.index)) or {x: [0.2, 0.2] for x in c})
    monkeypatch.setattr(tune, "search", lambda rows, f, n: seen.append(set(rows.index)) or [
        {"params": {"max_depth": 4, "min_samples_leaf": 10, "max_features": "sqrt", "n_estimators": 100},
         "fold_scores": [0.2, 0.2], "mean": 0.2, "std": 0.0}])
    tune.run(df, n_iter=1, n_splits=2, grid=GRID_CANDIDATES[:1])
    train_index, held_out = set(parts[0].index), set(parts[1].index) | set(parts[2].index)
    assert len(seen) == 3
    for rows in seen:
        assert rows == train_index and not rows & held_out


# ---- Search ----

def test_search_is_seeded_and_reproducible(parts):
    small = parts[0].iloc[:3000]
    small_folds = tune.make_folds(small, 2)
    space = {"max_depth": [4, 6], "min_samples_leaf": [50], "max_features": ["sqrt"], "n_estimators": [50]}
    first, second = (tune.search(small, small_folds, n_iter=2, space=space) for _ in range(2))
    assert first == second


def test_search_scores_match_a_manual_cross_validation(parts):
    small = parts[0].iloc[:3000]
    small_folds = tune.make_folds(small, 2)
    space = {"max_depth": [4], "min_samples_leaf": [50], "max_features": ["sqrt"], "n_estimators": [50]}
    row = tune.search(small, small_folds, n_iter=1, space=space)[0]
    manual = tune.cross_validate([tune.forest(row["params"])], small, small_folds)
    np.testing.assert_allclose(row["fold_scores"], next(iter(manual.values())), atol=1e-12)


# ---- One-standard-error rule ----

def _row(depth, leaf, mean, std=0.02, features="sqrt", trees=300, n=5):
    return {"params": {"max_depth": depth, "min_samples_leaf": leaf, "max_features": features, "n_estimators": trees},
            "fold_scores": [mean] * n, "mean": mean, "std": std}


def test_one_standard_error_rule_prefers_a_simpler_setting_within_noise():
    rows = [_row(None, 10, 0.290), _row(6, 50, 0.284), _row(4, 200, 0.270)]
    pick, bar = tune.one_standard_error_pick(rows)
    assert bar == pytest.approx(0.290 - 0.02 / 5 ** 0.5)
    assert pick["params"]["max_depth"] == 6  # within one SE of the best and simpler; depth 4 is below the bar


def test_one_standard_error_rule_keeps_the_best_when_nothing_else_is_close():
    rows = [_row(None, 10, 0.300, std=0.001), _row(6, 50, 0.284)]
    assert tune.one_standard_error_pick(rows)[0]["params"]["max_depth"] is None


def test_on_a_remaining_tie_more_trees_win():
    rows = [_row(6, 50, 0.284, trees=100), _row(6, 50, 0.284, trees=500)]
    assert tune.one_standard_error_pick(rows)[0]["params"]["n_estimators"] == 500


def test_fewer_columns_per_split_counts_as_simpler():
    rows = [_row(6, 50, 0.284, features=1.0), _row(6, 50, 0.284, features="sqrt")]
    assert tune.one_standard_error_pick(rows)[0]["params"]["max_features"] == "sqrt"


# ---- The committed result ----

def test_committed_result_used_the_planned_folds_and_draws(committed):
    assert committed["n_splits"] == tune.N_SPLITS and committed["n_iter"] == tune.N_ITER
    assert len(committed["search"]) == tune.N_ITER and committed["seed"] == config.SEED
    assert committed["search_space"] == json.loads(json.dumps(tune.SEARCH_SPACE))


def test_committed_choice_follows_the_one_standard_error_rule(committed):
    pick, bar = tune.one_standard_error_pick(committed["search"])
    assert pick["params"] == committed["chosen"] and bar == pytest.approx(committed["bar"])


def test_tuned_forest_joins_the_comparison(committed):
    tuned = [c for c in CANDIDATES if c not in GRID_CANDIDATES]
    assert len(tuned) == 1 and dict(tuned[0].params) == committed["chosen"]


def test_committed_report_matches_the_committed_result(committed):
    step2 = train.run(candidates=GRID_CANDIDATES, score_test=False)
    validation = {c.label: s.pr_auc for c, s in step2.validation.items()}
    ok, reason = reports_match(tune.REPORT.read_text(), tune.build_report(committed, validation))
    assert ok, reason
