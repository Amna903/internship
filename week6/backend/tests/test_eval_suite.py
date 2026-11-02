"""Week 6 Step 9: the evaluation suite reads the committed results and writes only to eval_suite/."""

from assistant.management.commands import evaluate_suite as suite


def test_clustering_summary_reads_the_committed_results():
    c = suite.clustering()
    assert c["real_patients"] == 5000 and c["control_planted_groups"] == 4
    assert 0 <= c["control_kmeans_ari_at_chosen_k"] <= 1


def test_baselines_are_week5_first_measurements():
    b = suite.baselines()
    assert b["agent_round1"]["tasks"] == 20 and isinstance(b["agent_round1_gate_passed"], bool)
    assert "recall@1" in b["retrieval"]


def test_report_covers_every_part(monkeypatch):
    result = {
        "started": "s",
        "finished": "f",
        "supervised": {
            "reproduced": True,
            "seconds": 1,
            "model_version": "1.0.0",
            "test_metrics_recorded_once": {"pr_auc": 0.28, "roc_auc": 0.66, "brier": 0.13},
            "baselines": {"floor_dummy": {"pr_auc": 0.164}},
        },
        "clustering": suite.clustering(),
        "baseline": suite.baselines(),
        "rag": {"questions": 23, "model": "m", "seeds": [42], "retrieval": {"mrr": 0.9}, "end_to_end": {"wrong": 0}},
        "agent": {"tasks": {"success": 9}, "red_team_cases": 11, "gate_passed": True, "recovery_passed": True},
    }
    text = suite.report(result)
    for heading in ("V1 Supervised", "V2 Clustering", "V3 RAG", "V4 Agent"):
        assert heading in text


def test_output_folder_is_separate_from_committed_results():
    assert suite.OUT.name == "eval_suite" and suite.OUT != suite.EVAL
