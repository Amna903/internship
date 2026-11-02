"""Week 4 Step 2 evidence (S3, S4, S5, S8): three algorithms compared on validation, a train versus
validation table with an overfitting warning, a simplicity order fixed before training, and no test
score anywhere in the comparison."""

import numpy as np
import pytest

from ml import config, train
from ml.data import generate
from ml.models import CANDIDATES, SIMPLICITY_ORDER, Candidate, build
from ml.preprocess import model_input
from ml.split import split
from ml.verify_release import confusion_count_tolerances, reports_match


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def comparison(df):
    return train.comparison_run(df)


def forests(result):
    return [c for c in result.validation if c.name == "random_forest"]


# ---- Three algorithms ----


def test_logistic_regression_random_forest_and_gradient_boosting_are_all_trained(comparison):
    trained = {c.name for c in comparison.validation}
    assert {"logreg_raw", "logreg_engineered", "random_forest", "gradient_boosting"} <= trained


def test_random_forest_uses_the_seed_no_class_weight_and_out_of_bag_scoring():
    forest = build(next(c for c in CANDIDATES if c.name == "random_forest")).named_steps["model"]
    assert forest.random_state == config.SEED
    assert forest.class_weight is None
    assert forest.oob_score is True


def test_random_forest_gives_identical_probabilities_when_trained_twice(df):
    """Run with several threads, the forest adds tree outputs in a varying order and the last digits
    change; n_jobs=1 makes it exact."""
    train_rows, validation, _ = split(df)
    candidate = next(c for c in CANDIDATES if c.name == "random_forest")
    X, y, X_val = model_input(train_rows), train_rows[config.LABEL], model_input(validation)
    first, second = (build(candidate).fit(X, y).predict_proba(X_val) for _ in range(2))
    np.testing.assert_array_equal(first, second)


# ---- Simplicity order, fixed before training ----


def test_complexity_follows_the_written_simplicity_order():
    rank = {name: i for i, name in enumerate(SIMPLICITY_ORDER)}
    for c in CANDIDATES:
        if c.family != "floor":
            assert c.complexity == rank[c.name], c.label


def test_a_tie_between_forest_and_boosting_goes_to_the_forest():
    forest = Candidate("improved", "random_forest", True, (), complexity=2)
    boosting = Candidate("improved", "gradient_boosting", True, (), complexity=3)
    scores = {forest: train.Scores(0.300, 0.7, 0.12, 0.16), boosting: train.Scores(0.304, 0.7, 0.12, 0.16)}
    assert train.select(scores) == forest


# ---- Train versus validation ----


def test_train_and_out_of_bag_scores_exist_for_the_right_models(comparison):
    assert set(comparison.train) == set(comparison.validation)
    assert set(comparison.out_of_bag) == set(forests(comparison))


def test_train_scores_are_really_computed_on_the_training_rows(df, comparison):
    train_rows, _, _ = split(df)
    c = comparison.chosen
    expected = train.score(train_rows[config.LABEL], comparison.fitted[c].predict_proba(model_input(train_rows))[:, 1])
    assert comparison.train[c] == expected


def test_report_table_states_every_models_train_validation_and_gap(comparison):
    report = train.build_report(comparison)
    for c in comparison.validation:
        if c.family == "floor":
            continue
        tr, va = comparison.train[c], comparison.validation[c]
        assert f"| {c.label} | {tr.pr_auc:.3f} | {va.pr_auc:.3f} | {tr.pr_auc - va.pr_auc:+.3f} |" in report


@pytest.mark.parametrize("train_pr, val_pr, warned", [(0.40, 0.30, True), (0.33, 0.30, False), (0.35, 0.30, False)])
def test_overfit_warning_threshold(train_pr, val_pr, warned):
    assert train.overfit_warning(train.Scores(train_pr, 0.7, 0.1, 0.16), train.Scores(val_pr, 0.7, 0.1, 0.16)) is warned


def test_warning_fires_on_a_tree_built_to_memorise_and_not_on_the_floor(df):
    from sklearn.pipeline import Pipeline
    from sklearn.tree import DecisionTreeClassifier

    from ml.preprocess import build_preprocessor

    train_rows, validation, _ = split(df)
    X, y = model_input(train_rows), train_rows[config.LABEL]
    X_val, y_val = model_input(validation), validation[config.LABEL]
    memoriser = Pipeline(
        [
            ("preprocess", build_preprocessor(engineered=True)),
            ("model", DecisionTreeClassifier(min_samples_leaf=1, random_state=config.SEED)),
        ]
    ).fit(X, y)
    floor = build(next(c for c in CANDIDATES if c.family == "floor")).fit(X, y)
    for model, expected in [(memoriser, True), (floor, False)]:
        tr = train.score(y, model.predict_proba(X)[:, 1])
        va = train.score(y_val, model.predict_proba(X_val)[:, 1])
        assert train.overfit_warning(tr, va) is expected


def test_forests_out_of_bag_score_is_a_fairer_estimate_than_their_training_score(comparison):
    """The point of the out-of-bag column: it lands near validation, while training score runs ahead."""
    for c in forests(comparison):
        tr, oob, va = comparison.train[c], comparison.out_of_bag[c], comparison.validation[c]
        assert abs(oob.pr_auc - va.pr_auc) < abs(tr.pr_auc - va.pr_auc), c.label


def test_report_says_the_warning_is_not_a_verdict(comparison):
    report = train.build_report(comparison)
    assert "a warning, not a verdict" in report
    assert "out-of-bag" in report


# ---- Step 4: the test set, scored once ----


def test_final_evaluation_scores_the_test_set_once_with_every_algorithm(comparison):
    names = {label.split(": ")[1].split(" (")[0] for label in comparison.test if ": " in label}
    assert {"logreg_raw", "logreg_engineered", "random_forest", "gradient_boosting"} <= names
    assert comparison.improvement is not None


def test_each_algorithm_has_a_confusion_matrix_over_all_test_rows(df, comparison):
    test_rows = len(split(df)[2])
    no_shows = int(split(df)[2][config.LABEL].sum())
    for label, (_cut, t, c) in comparison.per_model_test.items():
        assert c["tp"] + c["fp"] + c["fn"] + c["tn"] == test_rows, label
        assert c["tp"] + c["fn"] == no_shows, label
        assert t.recall == pytest.approx(c["tp"] / no_shows), label


def test_each_cut_off_is_the_models_own_validation_f1_best(df, comparison):
    _, validation, _ = split(df)
    X_val, y_val = model_input(validation), validation[config.LABEL]
    by_label = {c.label: c for c in comparison.fitted}
    for label, (cut, _, _) in comparison.per_model_test.items():
        candidate = by_label[label.split(": ", 1)[1]]
        assert cut == train.choose_threshold(y_val, comparison.fitted[candidate].predict_proba(X_val)[:, 1])


def test_choice_cut_offs_and_rival_do_not_depend_on_test_labels(df, comparison):
    _, _, test = split(df)
    flipped = df.copy()
    flipped.loc[test.index, config.LABEL] = ~flipped.loc[test.index, config.LABEL]
    again = train.run(flipped, cv=train.load_cv_scores())
    assert again.chosen == comparison.chosen and again.rival == comparison.rival
    assert {k: v[0] for k, v in again.per_model_test.items()} == {k: v[0] for k, v in comparison.per_model_test.items()}
    assert again.test != comparison.test  # the test scores do react, so test rows really were scored


def test_rival_is_the_best_other_model_by_cv_mean(comparison):
    others = [c for c in comparison.cv if c.family != "floor" and c.name != comparison.chosen.name]
    best_other = max(others, key=lambda c: np.mean(comparison.cv[c]))
    assert comparison.rival.endswith(best_other.label)


def test_report_states_the_test_set_history_and_the_cost_question(comparison):
    report = train.build_report(comparison)
    assert "exploratory evidence" in report
    assert "**Experimental selection (sections 1–2): did not read the test set.**" in report
    assert "**Release decision (section 7): test-informed.**" in report
    assert "already scored once in Week 3" in report and "fresh holdout" in report
    assert "## 5. What did choosing the simplest model cost?" in report
    assert train.simplicity_cost_verdict(comparison.improvement) in report


# ---- Release decision: keep serving the first release ----


def test_served_model_is_still_the_first_release():
    import json

    meta = json.loads((config.ARTIFACT_DIR / f"{config.MODEL_NAME}-{train.FIRST_RELEASE}.json").read_text())
    assert config.MODEL_VERSION == train.FIRST_RELEASE
    assert meta["estimator"] == train.SERVED_ESTIMATOR


def test_report_records_the_release_decision_and_its_three_points(comparison):
    report = train.build_report(comparison)
    assert "## 7. Release decision: keep serving" in report
    assert "not test-independent" in report and "champion/challenger" in report and "**Lesson.**" in report


def test_champion_challenger_numbers_are_the_cv_numbers(comparison):
    served = next(c for c in comparison.cv if c.label == train.SERVED_ESTIMATOR)
    report = train.build_report(comparison)
    assert f"challenger's mean was {np.mean(comparison.cv[comparison.chosen]):.3f}" in report
    assert f"against the champion's {np.mean(comparison.cv[served]):.3f}" in report
    # the challenger did not beat the champion by more than one standard error
    se = np.std(comparison.cv[served], ddof=1) / np.sqrt(5)
    assert np.mean(comparison.cv[comparison.chosen]) - np.mean(comparison.cv[served]) <= se


def test_confusion_count_tolerances_are_derived_from_the_0_005_rate_tolerance():
    # 650 no-shows, 3,302 attenders (the real test set): 0.005 x 650 -> 3 rows, 0.005 x 3,302 -> 16 rows
    cells = ["rf", "0.1943", "328", "886", "322", "2,416", "0.270", "0.505", "0.352", "0.665", "0.278"]
    assert confusion_count_tolerances(cells) == {"tp": 3, "fn": 3, "fp": 16, "tn": 16}


_SECTION = (
    "### Confusion matrix for each algorithm (test)\n"
    "| rf | 0.1943 | 328 | 886 | 322 | 2,416 | 0.270 | 0.505 | 0.352 | 0.665 | 0.278 |\n"
    "**About this test set.**"
)


def _moved(tp=328, fp=886, fn=322, tn="2,416"):
    return _SECTION.replace("| 328 | 886 | 322 | 2,416 |", f"| {tp} | {fp} | {fn} | {tn} |")


def test_a_one_step_cut_off_move_passes():
    # a step flags ~19 appointments: about 3 no-shows and 16 attenders
    assert reports_match(_SECTION, _moved(tp=331, fp=902, fn=319, tn="2,400"))[0]


def test_no_show_counts_beyond_3_rows_fail():
    assert not reports_match(_SECTION, _moved(tp=332, fn=318))[0]


def test_attender_counts_beyond_16_rows_fail():
    assert not reports_match(_SECTION, _moved(fp=903, tn="2,399"))[0]


def test_numbers_in_the_model_name_stay_exact_even_when_equal_to_a_count():
    named = _SECTION.replace("| rf |", "| random_forest (min_samples_leaf=328) |")
    assert not reports_match(named, named.replace("min_samples_leaf=328", "min_samples_leaf=329"))[0]


def test_counts_outside_cut_off_sections_must_be_exact():
    outside = _SECTION.replace("### Confusion matrix for each algorithm", "## 1. Validation")
    assert not reports_match(outside, outside.replace("| 328 |", "| 329 |"))[0]


def test_committed_comparison_report_is_up_to_date(comparison):
    ok, reason = reports_match(train.REPORT.read_text(), train.build_report(comparison))
    assert ok, reason


# ---- Same choice on every machine ----


def test_within_family_order_is_depth_then_leaf_then_more_trees():
    def forest(depth, leaf, trees=300):
        return Candidate(
            "improved",
            "random_forest",
            True,
            (("max_depth", depth), ("min_samples_leaf", leaf), ("n_estimators", trees)),
            complexity=2,
        )

    ordered = [forest(6, 50), forest(6, 20), forest(10, 50), forest(None, 50)]
    assert sorted(reversed(ordered), key=lambda c: c.within_family_simplicity) == ordered
    # More trees only steady the vote, they don't memorise: on a remaining tie, more trees win.
    assert forest(6, 50, 500).within_family_simplicity < forest(6, 50, 100).within_family_simplicity


def test_near_tied_forests_resolve_to_the_simpler_one_whatever_their_order():
    """The CI finding: two forests 0.0002 apart swapped places between Mac and Linux. With the
    within-family rule, a swap of near-tied scores can't change the choice."""
    deep = Candidate("improved", "random_forest", True, (("max_depth", None), ("min_samples_leaf", 50)), complexity=2)
    shallow = Candidate("improved", "random_forest", True, (("max_depth", 6), ("min_samples_leaf", 50)), complexity=2)
    for deep_score, shallow_score in [(0.2845, 0.281), (0.281, 0.2845)]:
        scores = {
            deep: train.Scores(deep_score, 0.65, 0.13, 0.16),
            shallow: train.Scores(shallow_score, 0.65, 0.13, 0.16),
        }
        assert train.select(scores) == shallow


def test_report_check_tolerates_platform_noise_but_not_a_different_choice():
    committed = "**Chosen: random_forest (max_depth=6)** | 0.281 | 69% |"
    assert reports_match(committed, committed.replace("0.281", "0.282").replace("69%", "68%"))[0]
    assert not reports_match(committed, committed.replace("max_depth=6", "max_depth=10"))[0]
    assert not reports_match("12,126 rows", "12,127 rows")[0]


def test_scores_keep_the_strict_tolerance():
    """PR-AUC, ROC-AUC and Brier move about 0.001 between machines: 0.002 allowed, no more."""
    row = "## 1. Validation\n| random_forest | 0.281 | 0.649 | 0.1301 |"
    assert reports_match(row, row.replace("0.281", "0.283"))[0]
    assert not reports_match(row, row.replace("0.281", "0.285"))[0]  # would pass the cut-off bar, not this one


def test_only_cut_off_figures_get_the_looser_tolerance():
    """The real CI case: recall at the decision threshold moved by 0.004 between Mac and Linux."""
    section = (
        "## 3. Decision threshold (chosen on validation)\n"
        "| validation (where it was chosen) | 0.1879 | 0.254 | 0.526 | 0.342 | 33.5% |\n"
        "## 4. Test set"
    )
    assert reports_match(section, section.replace("0.526", "0.522").replace("33.5%", "33.3%"))[0]
    assert not reports_match(section, section.replace("0.526", "0.516"))[0]
    assert not reports_match(section, section.replace("33.5%", "34.5%"))[0]
    # The same 0.004 move outside section 3 is a score, and fails.
    outside = section.replace("## 3. Decision threshold", "## 1. Validation")
    assert not reports_match(outside, outside.replace("0.526", "0.522"))[0]


# ---- Step 3 rule: choose by cross-validation, confirm on validation ----


def test_comparison_is_chosen_by_cross_validation_with_the_one_standard_error_rule(comparison):
    assert comparison.cv is not None
    chosen, bar = train.select_by_cv(comparison.cv)
    assert comparison.chosen == chosen and comparison.cv_bar == bar


def test_cv_scores_come_from_the_committed_tuning_result_for_every_real_candidate(comparison):
    real = {c for c in comparison.validation if c.family != "floor"}
    assert real <= set(comparison.cv)
    assert all(len(s) == 5 for s in comparison.cv.values())


def _lr(name, complexity, c=1.0):
    return Candidate("improved" if complexity else "baseline", name, complexity > 0, (("C", c),), complexity=complexity)


def test_cv_rule_picks_the_simplest_family_within_one_standard_error():
    raw, engineered = _lr("logreg_raw", 0), _lr("logreg_engineered", 1)
    # The bar uses the BEST model's standard error: engineered mean 0.287, SE 0.0054 -> bar 0.2816.
    cv = {raw: [0.28, 0.29, 0.27, 0.30, 0.285], engineered: [0.30, 0.27, 0.29, 0.28, 0.295]}
    assert train.select_by_cv(cv)[0] == raw  # raw (0.285) is above the bar, and simpler
    cv[engineered] = [0.33, 0.30, 0.32, 0.31, 0.325]
    assert train.select_by_cv(cv)[0] == engineered  # bar 0.3116: raw falls below it


def test_cv_rule_ignores_the_floor():
    floor = Candidate("floor", "floor_dummy", False)
    raw = _lr("logreg_raw", 0)
    assert train.select_by_cv({floor: [0.9] * 5, raw: [0.27] * 4 + [0.28]})[0] == raw


@pytest.mark.parametrize("validation, confirmed", [(0.275, True), (0.255, True), (0.250, False), (0.300, False)])
def test_validation_confirmation_check(validation, confirmed):
    folds = [0.27, 0.28, 0.26, 0.29, 0.275]  # mean 0.275, sd 0.0112: confirmed from 0.2526 to 0.2974
    assert train.confirmed_by_validation(folds, validation) is confirmed


def test_report_states_the_cv_rule_the_bar_and_the_confirmation(comparison):
    report = train.build_report(comparison)
    assert "choose by **cross-validation**" in report
    assert f"**{comparison.cv_bar:.3f}**" in report
    assert "**confirmed**" in report or "NOT confirmed" in report
