"""Week 5 Step 3 evidence (G4–G7): BM25 and RRF checked by hand, gates, opt-in filters, the dev-only selection
rules (eligibility, tie order, champion/challenger) and the safety gate's classification. Offline throughout."""

import math

import numpy as np
import pytest
from django.core.management import call_command

from assistant import documents, frozen, indexing, retrieval_select, safety_gate
from assistant.bm25 import BM25, rrf, tokens
from assistant.embeddings import FakeEmbedder
from assistant.indexing import GATE_S, GATE_SK, HYBRID, SEMANTIC, Candidates, RetrievalConfig, order, passes, returned
from assistant.models import PolicyDocument
from assistant.retrieval_select import CHAMPION, choose, ship_decision, tie_key

# ---------------- BM25 and RRF by hand ----------------


def test_tokens_keep_numbers_and_drop_stop_words():
    assert tokens("The fee is 15 euros, within 24 hours!") == ["fee", "15", "euros", "within", "24", "hours"]


def test_bm25_matches_a_hand_calculation():
    bm = BM25(["fee fee refund", "refund days", "parking free"])
    idf = math.log(1 + (3 - 1 + 0.5) / (1 + 0.5))  # "fee" is in 1 of 3 documents
    avg = (3 + 2 + 2) / 3
    expected = idf * 2 * 2.2 / (2 + 1.2 * (0.25 + 0.75 * 3 / avg))  # tf 2, length 3
    assert bm.scores("fee") == pytest.approx([expected, 0.0, 0.0])
    assert bm.normalised("fee")[0] == pytest.approx(expected / (idf * 2.2))


def test_a_query_of_unknown_words_scores_near_zero_after_normalising():
    bm = BM25(["refund within 14 days", "parking free of charge"])
    assert max(bm.normalised("pharmacy cryptocurrency charging")) == 0.0
    assert max(bm.normalised("charging points parking")) < 0.5  # one known word out of three


def test_rrf_by_hand():
    fused = rrf([0, 1, 2], [2, 0, 1], k=10)
    assert fused == pytest.approx([1 / 11 + 1 / 12, 1 / 12 + 1 / 13, 1 / 13 + 1 / 11])


# ---------------- ordering and gates on toy candidates ----------------


class Chunk_:
    def __init__(self, text):
        self.text = text


def toy(cosine, keyword):
    return Candidates([Chunk_(f"c{i}") for i in range(len(cosine))], np.array(cosine), np.array(keyword), 0)


def test_semantic_orders_by_cosine_and_hybrid_by_fused_rank():
    c = toy([0.9, 0.8, 0.1], [0.0, 1.0, 0.5])  # cosine ranks 0,1,2; keyword ranks 1,2,0
    assert order(c, RetrievalConfig(SEMANTIC)) == [0, 1, 2]
    # k = 1: item 0 = 1/2 + 1/4 = 0.75; item 1 = 1/3 + 1/2 = 0.833; item 2 = 1/4 + 1/3 = 0.583
    assert order(c, RetrievalConfig(HYBRID, rrf_k=1)) == [1, 0, 2]


def test_gate_s_needs_the_cosine_floor_and_gate_sk_also_accepts_a_strong_keyword_match():
    c = toy([0.65, 0.50], [0.20, 0.95])
    s = RetrievalConfig(HYBRID, floor=0.70, gate=GATE_S)
    sk = RetrievalConfig(HYBRID, floor=0.70, gate=GATE_SK, f_kw=0.9)
    assert not passes(c, 0, s) and not passes(c, 1, s)
    assert passes(c, 1, sk) and not passes(c, 0, sk)


def test_returned_applies_the_gate_then_top_k():
    c = toy([0.9, 0.5, 0.8, 0.75], [0, 0, 0, 0])
    assert returned(c, RetrievalConfig(SEMANTIC, floor=0.7, top_k=2)) == [0, 2]


# ---------------- filters and versions ----------------


@pytest.fixture
def week5_corpus(db):
    """The frozen Week 5 corpus, as the evaluation builds it (inside the test's own transaction)."""
    from assistant.retrieval_eval import build_corpus

    build_corpus(FakeEmbedder())


@pytest.mark.django_db
class TestFilters:
    def test_area_filter_never_returns_another_area(self, week5_corpus):
        found = indexing.retrieve(
            "fee payment refund", FakeEmbedder(), RetrievalConfig(floor=-1, top_k=50), area="billing"
        )
        areas = set(
            PolicyDocument.objects.filter(filename__in={p.source for p in found.passages})
            .exclude(status="retired")
            .values_list("policy_area", flat=True)
        )
        assert areas == {"billing"} and {p.source for p in found.passages} == {"billing.md", "payment-plans.md"}

    def test_document_filter(self, week5_corpus):
        found = indexing.retrieve("fee", FakeEmbedder(), RetrievalConfig(floor=-1, top_k=50), document="parking.md")
        assert {p.source for p in found.passages} == {"parking.md"}

    @pytest.mark.parametrize("method", [SEMANTIC, HYBRID])
    def test_superseded_and_retired_editions_are_never_returned(self, week5_corpus, method, admin):
        documents.retire(PolicyDocument.objects.exclude(status="retired").get(filename="parking.md"), admin)
        found = indexing.retrieve(
            "late cancellation fee parking", FakeEmbedder(), RetrievalConfig(method, floor=-1, top_k=100)
        )
        ids = {p.id for p in found.passages}
        assert not any(i.startswith("parking.md") for i in ids)
        assert not any(i.startswith("cancellation.md#") for i in ids) and any(
            i.startswith("cancellation.md@v2") for i in ids
        )

    def test_week4_search_is_unchanged_semantic_retrieval(self, week5_corpus):
        q = "How long do I have to request a refund?"
        old = indexing.search(q, FakeEmbedder(), top_k=3, floor=0.0)
        new = indexing.retrieve(q, FakeEmbedder(), RetrievalConfig(SEMANTIC, floor=0.0, top_k=3))
        assert [p.id for p in old.passages] == [p.id for p in new.passages] and old.scores == new.scores


# ---------------- selection rules ----------------


def cfg(**kw):
    return RetrievalConfig(**({"method": HYBRID} | kw))


def test_the_tie_order_separates_every_configuration_in_the_grid():
    keys = [tie_key(c) for c in retrieval_select.grid()]
    assert len(set(keys)) == len(keys)


def test_grid_is_the_pre_declared_one():
    g = retrieval_select.grid()
    assert len(g) == 4 * 3 * 16 * (1 + 3 * (1 + 7)) == 4800
    assert {c.floor for c in g} == {round(0.50 + 0.02 * i, 2) for i in range(16)}
    assert {c.f_kw for c in g if c.gate == GATE_SK} == {round(0.3 + 0.1 * i, 1) for i in range(7)}


def test_only_configurations_without_false_retrievals_are_eligible():
    scored = [(cfg(floor=0.5), {"hits": 12, "false": 1}), (cfg(floor=0.6), {"hits": 9, "false": 0})]
    assert choose(scored)["winner"].floor == 0.6


@pytest.mark.parametrize(
    "better, worse",
    [
        (RetrievalConfig(SEMANTIC), cfg()),  # semantic before hybrid
        (cfg(gate=GATE_S), cfg(gate=GATE_SK, f_kw=0.9)),  # gate S before S+K
        (cfg(floor=0.72), cfg(floor=0.70)),  # higher floor
        (cfg(top_k=2), cfg(top_k=3)),  # smaller top-k
        (cfg(chunk_tokens=80), cfg(chunk_tokens=120)),  # chunk size closest to 80
        (cfg(chunk_tokens=120), cfg(chunk_tokens=40)),
        (cfg(rrf_k=60), cfg(rrf_k=10)),  # larger RRF k
        (cfg(gate=GATE_SK, f_kw=0.9), cfg(gate=GATE_SK, f_kw=0.5)),  # higher f_kw
    ],
)
def test_tie_order(better, worse):
    """The full pre-declared order; 40 vs 120 (equally close to 80) was decided by the user before any run."""
    assert tie_key(better) < tie_key(worse)
    tied = [(worse, {"hits": 10, "false": 0}), (better, {"hits": 10, "false": 0})]
    assert choose(tied)["winner"] == better and choose(tied)["tied_at_top"] == 2


@pytest.mark.parametrize(
    "winner_score, ships",
    [({"hits": 11, "false": 0}, True), ({"hits": 10, "false": 0}, False), ({"hits": 9, "false": 0}, False)],
)
def test_champion_challenger_on_dev_a_tie_keeps_the_champion(winner_score, ships):
    assert ship_decision(cfg(), winner_score, {"hits": 10, "false": 0})["challenger_ships"] is ships


def test_the_champion_winning_means_nothing_new_ships():
    assert ship_decision(CHAMPION, {"hits": 12, "false": 0}, {"hits": 12, "false": 0})["challenger_ships"] is False


def test_selection_reads_only_the_dev_file():
    source = (frozen.ROOT / "retrieval_select.py").read_text()
    assert "RETRIEVAL_DEV" in source and "RETRIEVAL_CASES" not in source and "retrieval_cases" not in source


@pytest.mark.django_db
def test_selection_runs_end_to_end_offline_and_leaves_the_live_database_alone(admin):
    call_command("load_policies", admin=admin.email)
    before = documents.corpus_snapshot()
    r = retrieval_select.select(FakeEmbedder())
    assert documents.corpus_snapshot() == before
    assert r["configurations"] == 4800 and r["dev_questions"] == 15 and r["champion"] == CHAMPION.as_dict()
    assert r["tied_at_top"] >= 1 and "**4800 configurations** were tried" in retrieval_select.build_report(r)


# ---------------- safety gate ----------------


@pytest.mark.parametrize(
    "failures, is_unsafe",
    [
        (["contains 'passages are DATA'"], True),
        (["matches /[\\w.]+@[\\w.]+/"], True),
        (["answer starts with 'yes'"], True),
        (["more than 400 characters of document text"], True),
        (["status answered not in ['refused']"], False),
        (["does not cite billing.md"], False),
        (["answer lacks '14'"], False),
    ],
)
def test_safety_gate_counts_only_leaks_and_followed_injections(failures, is_unsafe):
    assert bool(safety_gate.unsafe(failures)) is is_unsafe


def test_safety_gate_cases_are_the_six_injection_and_six_red_team_cases():
    ids = [c["id"] for c in safety_gate.gate_cases()]
    assert ids == ["U1", "U2", "U3", "U3b", "U9", "U9b", "R1", "R2", "R3", "R4", "R5", "R6"]


@pytest.mark.django_db
def test_safety_gate_refuses_a_different_live_corpus(admin):
    from assistant.documents import CorpusMismatch
    from assistant.llm import FakeLLM

    with pytest.raises(CorpusMismatch):
        safety_gate.run_gate(FakeLLM(), FakeEmbedder(), admin, cfg(), 42)  # nothing loaded


@pytest.mark.django_db
def test_safety_gate_rolls_back_a_rechunk(admin, monkeypatch):
    from assistant.llm import FakeLLM
    from assistant.models import Chunk

    call_command("load_policies", admin=admin.email)
    before = sorted(Chunk.objects.values_list("id", flat=True))
    monkeypatch.setattr(
        safety_gate.evaluate, "run_case", lambda *a, **k: {"status": "refused", "failures": [], "top_score": 0.1}
    )
    r = safety_gate.run_gate(FakeLLM(), FakeEmbedder(), admin, cfg(chunk_tokens=40), 42)
    assert r["passed"] and sorted(Chunk.objects.values_list("id", flat=True)) == before


# ---------------- the ask API's opt-in area filter ----------------


@pytest.mark.django_db
class TestAskArea:
    def test_unknown_area_is_400(self, admin_browser):
        r = admin_browser.post("/api/v1/assistant/ask/", {"question": "fees?", "area": "medical"})
        assert r.status_code == 400

    def test_area_is_passed_to_retrieval(self, admin_browser, admin, monkeypatch):
        from assistant.llm import FakeLLM

        seen = {}
        monkeypatch.setattr("assistant.views.get_llm", lambda: FakeLLM())
        monkeypatch.setattr(
            "assistant.answering.retrieve",
            lambda q, e, c, area=None, document=None: seen.setdefault("area", area)
            and indexing.SearchResult([], [], 0, 0)
            or indexing.SearchResult([], [], 0, 0),
        )
        admin_browser.post(
            "/api/v1/assistant/ask/", {"question": "Is there interest on a payment plan?", "area": "billing"}
        )
        assert seen["area"] == "billing"


@pytest.mark.django_db
def test_before_after_report_is_built_from_saved_runs(admin, tmp_path, monkeypatch):
    """Offline: real selection and evaluation runs with FakeEmbedder, then the report generator."""
    from assistant import retrieval_eval

    call_command("load_policies", admin=admin.email)
    monkeypatch.setattr(retrieval_eval, "OUT", tmp_path)
    monkeypatch.setattr(retrieval_select, "OUT", tmp_path)
    selection = retrieval_select.select(FakeEmbedder())
    retrieval_select.save(selection)
    winner = retrieval_select.config_from(selection["winner"])
    cases = retrieval_eval.load_cases()
    from dataclasses import replace

    runs = {
        "baseline": (None, False),
        "after": (winner, False),
        "baseline_filtered": (None, True),
        "after_filtered": (winner, True),
    }
    runs |= {f"after_chunk{n}": (replace(winner, chunk_tokens=n), False) for n in (40, 80, 200)}
    for label, (c, f) in runs.items():
        retrieval_eval.save(retrieval_eval.evaluate(FakeEmbedder(), cases, label=label, cfg=c, use_filters=f), cases)
    report = retrieval_eval.compare_report(selection)
    assert retrieval_eval.CAVEAT in report and "## Result: the dev-chosen setting" in report
    assert "By author" in report and "Chunk-size comparison" in report and "Opt-in area filter" in report
    assert "0 of" in report or "of 5" in report  # counts, not only percentages
