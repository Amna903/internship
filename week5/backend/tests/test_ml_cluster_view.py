"""Week 4 Step 8 evidence (U6, U7, U9, A6, A8): PCA picture data, neutral descriptions built from the
numbers, real-data clusters shown only as misleading, and the meaningful-versus-misleading explanation."""

import re

import pytest

from ml import cluster_view
from ml.verify_release import reports_match

BANNED = ["risk", "patient type", "diagnos", "condition", "illness", "disease", "sick", "health", "unreliable",
          "lazy", "bad", "good", "compliant", "non-compliant", "vulnerable", "high-risk", "low-risk", "age",
          "young", "old", "elderly", "gender", "income", "poor", "rich"]


@pytest.fixture(scope="module")
def view():
    return cluster_view.build()


def all_descriptions(view):
    return [c["description"] for c in view["control"]["clusters"] + view["real"]["misleading_clusters"]]


def test_descriptions_use_no_health_or_personal_words(view):
    for text in all_descriptions(view):
        for word in BANNED:
            assert not re.search(rf"\b{re.escape(word)}", text.lower()), (word, text)


def test_descriptions_are_built_from_the_numbers(view):
    """Every phrase comes from PHRASES and points the right way for that cluster's mean."""
    import pandas as pd
    from ml import cluster_features
    from ml.data import generate
    table = cluster_features.patient_table(generate())
    overall, spread = table.mean(), table.std(ddof=0)
    for c in view["real"]["misleading_clusters"]:
        for feature, (higher, lower) in cluster_view.PHRASES.items():
            z = (c["profile"][feature] - overall[feature]) / spread[feature]
            text = c["description"].lower()
            if higher.lower() in text:
                assert z >= cluster_view.MENTION_SD
            if lower.lower() in text:
                assert z <= -cluster_view.MENTION_SD


def test_cluster_sizes_add_up(view):
    assert sum(c["size"] for c in view["control"]["clusters"]) == view["control"]["patients"]
    assert sum(c["size"] for c in view["real"]["misleading_clusters"]) == view["real"]["patients"]


def test_pca_points_are_control_data_with_two_axes(view):
    points = view["control"]["points"]
    assert len(points) == view["control"]["patients"]
    assert set(points[0]) == {"x", "y", "cluster", "planted_habit"}
    assert 0 < sum(view["control"]["pca_variance"]) <= 1


def test_real_clusters_appear_only_under_the_misleading_heading(view):
    report = cluster_view.build_report(view)
    assert "## 3. Clusters K-Means formed anyway on the real data: misleading, not supported by the baseline" in report
    assert not any(view["real"]["structure_found"].values())


def test_report_explains_meaningful_vs_misleading_and_why_exploratory(view):
    report = cluster_view.build_report(view)
    assert "## 4. Meaningful versus misleading clusters" in report
    assert "## 5. Why clusters are exploratory, not categories of people" in report
    assert "always returns the number of groups it is asked for" in report


def test_committed_files_are_up_to_date(view):
    ok, reason = reports_match(cluster_view.RESULT.read_text(), cluster_view.to_json(view))
    assert ok, reason
    ok, reason = reports_match(cluster_view.REPORT.read_text(), cluster_view.build_report(view))
    assert ok, reason
