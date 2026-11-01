"""Week 5 Step 2: the retrieval-only harness (V2, V3). Metrics are checked by hand on toy rankings; the
frozen corpus is built and rolled back without touching the live database; no model is ever called.
Offline: FakeEmbedder."""

import pytest
from django.core.management import CommandError, call_command

from assistant import frozen, retrieval_eval
from assistant.documents import CorpusMismatch, corpus_snapshot
from assistant.embeddings import FakeEmbedder
from assistant.models import Chunk, DocumentVersion, PolicyDocument
from assistant.retrieval_eval import Ranked, aggregate, score_case

ANS = {"id": "T1", "answerable": True, "evidence": [{"document": "a.md", "version": 1, "quote": "The fee is 10 euros."}]}
MULTI = {"id": "T2", "answerable": True, "evidence": [{"document": "a.md", "version": 1, "quote": "alpha beta"},
                                                     {"document": "b.md", "version": 1, "quote": "gamma delta"}]}
NONE = {"id": "T3", "answerable": False, "evidence": []}


def ranked(*texts, scores=None, docs=None):
    return Ranked(list(texts), docs or ["a.md"] * len(texts), scores or [0.9 - 0.1 * i for i in range(len(texts))])


class TestScoringByHand:
    def test_hit_at_rank_two(self):
        r = score_case(ANS, ranked("Nothing here.", "x THE FEE IS  10 euros. y", "z"), floor=0.7, top_k=2)
        assert (r["first_rank"], r["reciprocal_rank"]) == (2, 0.5)
        assert (r["recall@1"], r["recall@3"], r["hit@3"]) == (False, True, True)
        assert r["shipped_hit"] is True  # rank 2, score 0.8 >= 0.7, inside top-k 2

    def test_partial_quote_is_not_a_hit(self):
        r = score_case(ANS, ranked("The fee is 10", "euros."), floor=0.0, top_k=5)
        assert r["first_rank"] is None and not r["recall@5"]

    def test_multi_doc_needs_every_quote_for_recall_but_one_for_a_hit(self):
        r = score_case(MULTI, ranked("alpha beta", "x", "y", "gamma delta", docs=["a.md", "c.md", "c.md", "b.md"]),
                       floor=0.0, top_k=2)
        assert r["hit@1"] and not r["recall@3"] and r["recall@5"]
        assert not r["doc_recall@3"] and r["doc_recall@5"]
        assert r["shipped_hit"] is False  # only one of the two quotes is in the top 2

    def test_below_the_floor_is_not_returned_as_shipped(self):
        r = score_case(ANS, ranked("The fee is 10 euros.", scores=[0.65]), floor=0.7, top_k=2)
        assert r["recall@1"] and r["shipped_returned"] == 0 and not r["shipped_hit"]

    def test_unanswerable_false_retrieval_follows_the_floor(self):
        assert score_case(NONE, ranked("x", scores=[0.71]), 0.7, 2)["false_retrieval"] is True
        assert score_case(NONE, ranked("x", scores=[0.69]), 0.7, 2)["false_retrieval"] is False

    def test_aggregate(self):
        rows = [score_case(ANS, ranked("The fee is 10 euros."), 0.0, 2),
                score_case(ANS, ranked("no", "no", "no", "The fee is 10 euros."), 0.0, 2),
                score_case(NONE, ranked("x", scores=[0.9]), 0.7, 2)]
        agg = aggregate(rows)
        assert agg["recall@1"] == 0.5 and agg["recall@5"] == 1.0 and agg["mrr"] == pytest.approx((1 + 0.25) / 2)
        assert agg["false_retrieval_rate"] == 1.0 and (agg["answerable"], agg["unanswerable"]) == (2, 1)


@pytest.fixture
def live(db, admin):
    from django.core.management import call_command
    call_command("load_policies", admin=admin.email)


@pytest.mark.django_db
class TestRun:
    def test_corpus_is_built_checked_and_rolled_back(self, live):
        before = (corpus_snapshot(), Chunk.objects.count(), PolicyDocument.objects.count(), DocumentVersion.objects.count())
        result = retrieval_eval.evaluate(FakeEmbedder(), retrieval_eval.load_cases(), label="test")
        after = (corpus_snapshot(), Chunk.objects.count(), PolicyDocument.objects.count(), DocumentVersion.objects.count())
        assert before == after  # the live database is untouched
        assert {r["filename"]: (r["version"], r["sha256"]) for r in result["corpus"]} == frozen.WEEK5_CORPUS

    def test_v1_of_cancellation_is_never_retrieved(self, live):
        result = retrieval_eval.evaluate(FakeEmbedder(), retrieval_eval.load_cases(), label="test")
        ids = {p for r in result["cases"] for p in r["top_passages"]}
        assert any(p.startswith("cancellation.md@v2#") for p in ids)
        assert not any(p.startswith("cancellation.md#") for p in ids)

    def test_every_question_is_scored_and_grouped(self, live):
        cases = retrieval_eval.load_cases()
        result = retrieval_eval.evaluate(FakeEmbedder(), cases, label="test")
        assert len(result["cases"]) == len(cases) == result["overall"]["questions"]
        assert set(result["by_author"]) == {"user", "assistant"} and "unanswerable" in result["by_category"]

    def test_no_model_is_called(self, live, monkeypatch):
        monkeypatch.setattr("assistant.llm.get_llm", lambda: pytest.fail("retrieval evaluation must not call a model"))
        monkeypatch.setattr("assistant.llm.OllamaClient.chat", lambda *a, **k: pytest.fail("no chat call"), raising=False)
        retrieval_eval.evaluate(FakeEmbedder(), retrieval_eval.load_cases(), label="test")

    def test_a_tampered_corpus_file_fails_loudly(self, live, monkeypatch):
        files = list(frozen.WEEK5_CORPUS_FILES)
        files[-1] = ("cancellation.md", 2, "corpus_week5/parking.md", "cancellation")  # wrong file for v2
        monkeypatch.setattr(frozen, "WEEK5_CORPUS_FILES", files)
        with pytest.raises(CorpusMismatch):
            retrieval_eval.evaluate(FakeEmbedder(), retrieval_eval.load_cases(), label="test")
        assert corpus_snapshot() and len(corpus_snapshot()) == 6  # still rolled back

    def test_a_changed_corpus_file_fails_loudly(self, live, monkeypatch):
        pins = dict(frozen.WEEK5_FROZEN_SHA256) | {"corpus_week5/parking.md": "0" * 64}
        monkeypatch.setattr(frozen, "WEEK5_FROZEN_SHA256", pins)
        with pytest.raises(CorpusMismatch, match="parking.md"):
            retrieval_eval.evaluate(FakeEmbedder(), retrieval_eval.load_cases(), label="test")

    def test_report_states_the_caveat_and_no_model(self, live):
        cases = retrieval_eval.load_cases()
        report = retrieval_eval.build_report(retrieval_eval.evaluate(FakeEmbedder(), cases, label="test"), cases)
        assert retrieval_eval.CAVEAT in report and "no language model is called" in report

    def test_command_writes_results_and_refuses_bad_labels(self, live, tmp_path, monkeypatch):
        monkeypatch.setattr(retrieval_eval, "OUT", tmp_path)
        call_command("evaluate_retrieval", label="unit")
        assert (tmp_path / "retrieval_unit.json").exists() and (tmp_path / "retrieval_unit.md").exists()
        with pytest.raises(CommandError):
            call_command("evaluate_retrieval", label="../x")
