"""Week 5 Step 4: the generation harness (V4–V6). Oracle contexts, per-run scoring by hand, majority, and an
offline end-to-end run that is rolled back. Fake model and FakeEmbedder."""


import pytest
from django.core.management import call_command

from assistant import documents, frozen, generation_eval
from assistant.embeddings import FakeEmbedder
from assistant.generation_eval import aggregate, majority, oracle_context, score_run
from assistant.indexing import candidates
from assistant.llm import FakeLLM
from assistant.retrieval_eval import build_corpus, norm

CASES = generation_eval.load_cases()
KEYS = generation_eval.load_keys()


@pytest.fixture
def corpus(db):
    build_corpus(FakeEmbedder())


@pytest.mark.django_db
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_oracle_context_has_the_gold_text_plus_exactly_one_distractor(corpus, case):
    ctx = oracle_context(case, candidates(case["question"], FakeEmbedder()))
    if not case["answerable"]:
        assert len(ctx) == 2
        return
    quotes = [norm(e["quote"]) for e in case["evidence"]]
    assert all(any(q in norm(p.text) for p in ctx) for q in quotes)          # every quote is there
    distractors = [p for p in ctx if not any(q in norm(p.text) for q in quotes)]
    assert len(distractors) == 1 and len(ctx) <= len(quotes) + 1
    assert not any(p.id.startswith("cancellation.md#") for p in ctx)          # never the superseded edition


A01 = next(c for c in CASES if c["id"] == "A01")
U09 = next(c for c in CASES if c["id"] == "U09")
GOLD = {"billing.md#0": "Visit fees are charged after the appointment. A refund can be requested within 14 days of a "
                        "payment, in the patient app or at the front desk.", "parking.md#0": "Park free for 3 hours."}


@pytest.mark.parametrize("status, answer, cited, expect", [
    ("answered", "A refund can be requested within fourteen days.", ["billing.md#0"],
     {"key_fact_ok": True, "citation_recall": True, "gold_citations": 1, "answered_wrong": False}),
    ("answered", "A refund can be requested within 30 days.", ["billing.md#0"],
     {"key_fact_ok": False, "answered_wrong": True, "citation_recall": True}),
    ("answered", "A refund can be requested within 14 days.", ["parking.md#0"],
     {"key_fact_ok": True, "citation_recall": False, "gold_citations": 0}),
    ("insufficient_information", "", [], {"key_fact_ok": False, "false_abstention": True, "answered_wrong": False}),
])
def test_score_run_by_hand(status, answer, cited, expect):
    r = score_run(A01, KEYS["A01"], status, answer, [{"passage_id": p, "quote": "x"} for p in cited], GOLD)
    assert {k: r[k] for k in expect} == expect


def test_unanswerable_scoring():
    assert score_run(U09, None, "insufficient_information", "", [], {})["abstained"] is True
    assert score_run(U09, None, "answered", "Yes.", [], {})["abstained"] is False


def test_majority_is_two_of_three():
    assert majority([{"x": True}, {"x": True}, {"x": False}], "x") and not majority([{"x": True}, {}, {"x": False}], "x")


def test_aggregate_counts():
    runs = {"A01": [score_run(A01, KEYS["A01"], "answered", "within 14 days", [{"passage_id": "billing.md#0"}], GOLD)
                    | {"rejected_citations": 0, "groundedness": 0.9, "tokens": 10, "seconds": 1.0}] * 3,
            "U09": [score_run(U09, None, "answered", "Yes.", [], {})
                    | {"rejected_citations": 0, "groundedness": None, "tokens": 5, "seconds": 1.0}] * 3}
    agg = aggregate([A01, U09], runs)
    assert (agg["key_fact_ok"], agg["abstained"], agg["gold_citations"], agg["citations"]) == (1, 0, 3, 3)


@pytest.mark.django_db
def test_end_to_end_offline_is_rolled_back_and_reports_both_modes(admin, tmp_path, monkeypatch):
    call_command("load_policies", admin=admin.email)
    before = documents.corpus_snapshot()
    r = generation_eval.evaluate(FakeLLM(), FakeEmbedder(), 42, CASES)
    assert documents.corpus_snapshot() == before
    assert set(r["modes"]) == {"A", "B"} and len(r["modes"]["A"]["runs"]) == 23
    assert all(len(runs) == 3 for runs in r["modes"]["B"]["runs"].values())
    assert {x["filename"] for x in r["corpus"]} == set(frozen.WEEK5_CORPUS)
    monkeypatch.setattr(generation_eval, "OUT", tmp_path)
    report = generation_eval.build_report(r, CASES)
    assert "Reporting only: nothing was tuned" in report and "By author" in report and generation_eval.CAVEAT in report


def test_harness_reads_only_frozen_files():
    src = (frozen.ROOT / "generation_eval.py").read_text()
    assert "RETRIEVAL_CASES" in src and "GENERATION_KEYS" in src and "open(" not in src
