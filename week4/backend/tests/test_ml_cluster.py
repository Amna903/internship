"""Week 4 Step 7 evidence (U2, U3, U5, U8, A5, A7): two methods, the k rule, an appointment-level
reshuffle baseline that keeps what it should, false-pattern checks, a positive control whose labels are
only used to score recovery, and wording computed from the numbers."""

import inspect

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import adjusted_rand_score

from ml import cluster, cluster_control, cluster_features, config, holdout
from ml.data import generate
from ml.verify_release import reports_match


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def appointments(df):
    return df[["patient_id", "lead_time_days", "visit_type", "booking_channel", "appointment_hour"]]


@pytest.fixture(scope="module")
def control():
    return cluster_control.generate_control()


@pytest.fixture(scope="module")
def committed():
    return cluster.load_result()


# ---- Positive control ----

def test_control_is_seeded_and_separate(control, df):
    again = cluster_control.generate_control()
    pd.testing.assert_frame_equal(control[0], again[0])
    assert cluster_control.CONTROL_SEED not in (config.SEED, holdout.HOLDOUT_SEED)
    ids = set(control[0]["patient_id"])
    assert not ids & set(df["patient_id"]) and min(ids) > holdout.ID_OFFSET + holdout.N_PATIENTS


def test_control_never_touches_the_main_generator():
    assert "data import" not in inspect.getsource(cluster_control) and "generate(" not in inspect.getsource(cluster_control)


def test_planted_labels_are_never_clustering_inputs(control, monkeypatch):
    """Scramble the planted labels: if they were an input, silhouettes or the chosen k would change.
    Only the recovery scores (ARI) may react."""
    appointments, truth = control
    original = cluster.analyse_control()
    scrambled = pd.Series(np.random.default_rng(0).permutation(truth.to_numpy()), index=truth.index, name=truth.name)
    monkeypatch.setattr(cluster_control, "generate_control", lambda: (appointments, scrambled))
    again = cluster.analyse_control()
    assert again["silhouette"] == original["silhouette"] and again["chosen_k"] == original["chosen_k"]
    assert again["methods"] != original["methods"]


def test_appointment_count_does_not_depend_on_the_habit(control):
    appointments, truth = control
    per_patient = appointments.groupby("patient_id").size()
    means = per_patient.groupby(truth.loc[per_patient.index]).mean()
    assert means.max() - means.min() < 0.3


# ---- Reshuffle baseline keeps what it should ----

@pytest.fixture(scope="module")
def reshuffled(appointments):
    return cluster.reshuffle_appointments(appointments, np.random.default_rng(config.SEED))


def test_reshuffle_keeps_each_patients_number_of_appointments(appointments, reshuffled):
    pd.testing.assert_series_equal(appointments.groupby("patient_id").size(), reshuffled.groupby("patient_id").size())


def test_reshuffle_keeps_every_column_distribution(appointments, reshuffled):
    for column in ["lead_time_days", "visit_type", "booking_channel", "appointment_hour"]:
        assert sorted(appointments[column]) == sorted(reshuffled[column])


def test_reshuffle_keeps_the_mechanical_links(df, reshuffled):
    real, shuffled = cluster_features.patient_table(df), cluster_features.patient_table(reshuffled)
    assert abs(real["phone_share"].corr(real["app_share"]) - shuffled["phone_share"].corr(shuffled["app_share"])) < 0.05
    singles = shuffled[shuffled["appointments"] == 1]
    assert singles[["telehealth_share", "phone_share", "app_share"]].isin([0.0, 1.0]).all().all()


def test_reshuffle_destroys_planted_habits(control):
    """The baseline removes habits: on the control, reshuffled patients no longer match their habit."""
    appointments, truth = control
    shuffled = cluster.reshuffle_appointments(appointments, np.random.default_rng(config.SEED))
    table = cluster_features.patient_table(shuffled)
    labels = cluster.labels_for(cluster_features.scaled(table)[0], "k-means", 4)
    assert abs(adjusted_rand_score(truth.loc[table.index], labels)) < 0.02


# ---- Rules ----

@pytest.mark.parametrize("silhouettes, expected", [({2: 0.30, 3: 0.35, 4: 0.34}, 3), ({2: 0.345, 3: 0.35, 4: 0.30}, 2),
                                                   ({2: 0.10, 3: 0.20, 4: 0.40}, 4)])
def test_k_rule_best_silhouette_and_fewer_clusters_on_a_tie(silhouettes, expected):
    assert cluster.choose_k(silhouettes) == expected


@pytest.mark.parametrize("ari, word", [(0.95, "recovered well"), (0.8, "recovered well"), (0.52, "partially recovered"),
                                       (0.3, "weakly recovered"), (0.05, "not recovered")])
def test_recovery_words(ari, word):
    assert cluster.recovery_word(ari) == word


@pytest.mark.parametrize("ari, note", [(0.52, "0.52 sits just above the 0.5 threshold, so the 'partially recovered' label is borderline"),
                                       (0.47, "0.47 sits just below the 0.5 threshold"), (0.65, "")])
def test_borderline_labels_are_flagged(ari, note):
    assert (note in cluster.borderline_note(ari)) if note else cluster.borderline_note(ari) == ""


def test_report_flags_the_actual_result_as_borderline(committed):
    best = max(committed["control"]["methods"][m]["ari_at_chosen_k"] for m in cluster.METHODS)
    assert cluster.borderline_note(best).strip() in cluster.build_report(committed)


def test_false_pattern_check_flags_a_cluster_of_one_appointment_patients(df):
    table = cluster_features.patient_table(df)
    labels = (table["appointments"] == 1).astype(int).to_numpy()
    fp = cluster.false_pattern_checks(table, labels)
    assert fp["checks"]["mostly one-appointment patients"]


def test_false_pattern_check_names_appointment_count_when_it_drives_the_split(df):
    table = cluster_features.patient_table(df)
    labels = (table["appointments"] > table["appointments"].median()).astype(int).to_numpy()
    assert cluster.false_pattern_checks(table, labels)["checks"]["split mainly by appointment count"]


# ---- The committed result ----

def test_real_verdicts_follow_the_rule(committed):
    for m in cluster.METHODS:
        v = committed["real"]["methods"][m]
        assert v["structure_found"] == (v["silhouette"] > v["baseline_bar"])
        assert v["baseline_bar"] == pytest.approx(np.percentile(committed["real"]["baseline"][m], cluster.BASELINE_PERCENTILE))
        assert len(committed["real"]["baseline"][m]) == cluster.BASELINE_RUNS


def test_chosen_k_follows_the_rule(committed):
    for part in ("real", "control"):
        for m in cluster.METHODS:
            assert committed[part]["chosen_k"][m] == cluster.choose_k(committed[part]["silhouette"][m])


def test_control_recovery_beats_chance_and_the_wording_matches(committed):
    best = max(committed["control"]["methods"][m]["ari_at_chosen_k"] for m in cluster.METHODS)
    assert best > 0.2
    assert f"were {cluster.recovery_word(best)} (best ARI {best:.3f})" in cluster.build_report(committed)


def test_report_says_thresholds_were_set_after_seeing_the_result(committed):
    report = cluster.build_report(committed)
    assert "**These thresholds were set after seeing this result.**" in report
    assert "### Diagnostic (not the result)" in report


def test_committed_report_matches_the_committed_result(committed):
    ok, reason = reports_match(cluster.REPORT.read_text(), cluster.build_report(committed))
    assert ok, reason
