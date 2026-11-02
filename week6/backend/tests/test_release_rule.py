"""Pins the champion/challenger rule frozen on 2026-11-01 (ml/release_rule.py), so it can't change after
seeing results without this test changing in the same commit."""

import pytest

from ml import release_rule


def test_rule_is_dated_as_frozen():
    assert release_rule.FROZEN_ON == "2026-11-01"


def test_challenger_needs_a_lead_beyond_one_standard_error_of_the_champion():
    champion = [0.27, 0.28, 0.26, 0.29, 0.275]  # mean 0.275, SE 0.005
    assert not release_rule.challenger_wins(champion, [c + 0.004 for c in champion])
    assert release_rule.challenger_wins(champion, [c + 0.006 for c in champion])


def test_week4_case_the_challenger_did_not_win():
    """Week 4's numbers (tuning.json): raw LR (challenger) against the served engineered LR (champion)."""
    import json

    from ml import tune

    result = json.loads(tune.RESULT.read_text())
    folds = {g["label"]: g["fold_scores"] for g in result["grid_cv"]}
    assert not release_rule.challenger_wins(folds["logreg_engineered (C=0.1)"], folds["logreg_raw (C=10.0)"])


def test_champion_and_challenger_must_share_folds():
    with pytest.raises(ValueError):
        release_rule.challenger_wins([0.3] * 5, [0.3] * 3)


@pytest.mark.parametrize(
    "a, b, applies",
    [
        ("logreg_raw", "logreg_engineered", False),
        ("logreg_engineered", "random_forest", True),
        ("random_forest", "gradient_boosting", False),
    ],
)
def test_simplicity_only_separates_models_that_differ_in_explainability(a, b, applies):
    assert release_rule.simplicity_applies(a, b) is applies


@pytest.mark.parametrize("inputs_changed, expected", [(False, "1.1.0"), (True, "2.0.0")])
def test_version_numbering(inputs_changed, expected):
    assert release_rule.next_version("1.0.0", inputs_changed) == expected
