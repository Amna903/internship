"""Week 5 Step 2: the frozen retrieval corpus, the 23-question evaluation set and the dev set.

Guards that they are unchanged (hashes pinned before any Step 3 design), that every label is valid under the
hit rule (a one-sentence quote, found whole), that the hit rule is fair at every chunk size Step 3 may try,
and that the dev set is independent of the evaluation set (no shared question, no shared evidence sentence:
the Week 4 A1/A6 lesson)."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from assistant import frozen
from assistant.chunking import chunk, sentences

ASSISTANT = Path(frozen.__file__).resolve().parent
TEXT = {(name, version): (ASSISTANT / file).read_text() for name, version, file, _ in frozen.WEEK5_CORPUS_FILES}
CHUNK_SIZES = range(20, 401, 20)  # wider than anything Step 3 will compare; extend if it ever goes beyond


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def load(path):
    return json.loads(path.read_text())["cases"]


EVAL, DEV = load(frozen.RETRIEVAL_CASES), load(frozen.RETRIEVAL_DEV)


def evidence_sentence(e: dict) -> str:
    """The one sentence of the named edition that contains the quote (the hit rule needs exactly this)."""
    found = [norm(s) for s in sentences(TEXT[(e["document"], e["version"])]) if norm(e["quote"]) in norm(s)]
    assert found, f"quote not inside one sentence of {e['document']} v{e['version']}: {e['quote']!r}"
    return found[0]


# ---------------- frozen ----------------


@pytest.mark.parametrize("relative", sorted(frozen.WEEK5_FROZEN_SHA256))
def test_week5_frozen_file_is_unchanged(relative):
    assert hashlib.sha256((ASSISTANT / relative).read_bytes()).hexdigest() == frozen.WEEK5_FROZEN_SHA256[relative]


def test_every_corpus_file_on_disk_is_pinned_and_in_the_manifest():
    on_disk = {f"corpus_week5/{p.name}" for p in (ASSISTANT / "corpus_week5").glob("*.md")}
    assert on_disk <= set(frozen.WEEK5_FROZEN_SHA256)
    assert on_disk == {f for _, _, f, _ in frozen.WEEK5_CORPUS_FILES if f.startswith("corpus_week5/")}


def test_corpus_is_the_six_week4_policies_plus_six_new_and_cancellation_v2():
    names = [(n, v) for n, v, _, _ in frozen.WEEK5_CORPUS_FILES]
    assert len({n for n, _ in names}) == 12 and names[-1] == ("cancellation.md", 2)
    assert frozen.WEEK5_CORPUS["cancellation.md"][0] == 2


def test_new_policies_stay_administrative():
    clinical = re.compile(r"\b(diagnos\w*|dose|dosage|medication|symptom\w*|treatment|prescri\w*)\b", re.I)
    for name, version, file, _ in frozen.WEEK5_CORPUS_FILES:
        if file.startswith("corpus_week5/"):
            assert not clinical.search(TEXT[(name, version)]), name


# ---------------- the evaluation set ----------------


def test_at_least_twenty_cases_with_unique_ids():
    assert len(EVAL) >= 20 and len({c["id"] for c in EVAL}) == len(EVAL)


def test_user_wrote_at_least_ten_and_authors_are_marked():
    assert {c["author"] for c in EVAL} == {"user", "assistant"}
    assert sum(c["author"] == "user" for c in EVAL) >= 10


def test_every_category_is_covered():
    assert {c["category"] for c in EVAL} == {
        "direct",
        "paraphrase",
        "keyword",
        "multi_doc",
        "area_hint",
        "current_version",
        "unanswerable",
    }


@pytest.mark.parametrize("case", EVAL + DEV, ids=lambda c: c["id"])
def test_labels_follow_the_hit_rule(case):
    if not case["answerable"]:
        assert case["category"] == "unanswerable" and case["evidence"] == []
        return
    assert case["evidence"]
    for e in case["evidence"]:
        evidence_sentence(e)
        assert frozen.WEEK5_CORPUS[e["document"]][0] == e["version"], "evidence must come from the current edition"


@pytest.mark.parametrize("case", [c for c in EVAL + DEV if c["category"] == "current_version"], ids=lambda c: c["id"])
def test_current_version_quotes_exist_only_in_v2(case):
    v1 = norm(TEXT[("cancellation.md", 1)])
    assert all(norm(e["quote"]) not in v1 for e in case["evidence"])


@pytest.mark.parametrize("size", CHUNK_SIZES)
def test_every_quote_is_whole_in_some_chunk_at_every_chunk_size(size):
    """Why one-sentence quotes are fair to small chunks: the chunker never splits a sentence."""
    for c in EVAL + DEV:
        for e in c["evidence"]:
            chunks = chunk(TEXT[(e["document"], e["version"])], max_tokens=size)
            assert any(norm(e["quote"]) in norm(ch) for ch in chunks), (c["id"], size)


@pytest.mark.parametrize("case", [c for c in EVAL if c["id"] in {"U09", "U10", "U11"}], ids=lambda c: c["id"])
def test_user_unanswerable_topics_are_absent_from_the_corpus(case):
    terms = {"U09": r"electric|charging point|\bev\b", "U10": r"pharmac", "U11": r"holiday"}[case["id"]]
    assert not any(re.search(terms, t, re.I) for t in TEXT.values())


# ---------------- dev set independence ----------------


def test_dev_and_eval_share_no_question():
    assert not {norm(c["question"]) for c in DEV} & {norm(c["question"]) for c in EVAL}


def test_no_dev_question_shares_an_evidence_sentence_with_an_eval_question():
    eval_sentences = {evidence_sentence(e): c["id"] for c in EVAL for e in c["evidence"]}
    shared = [
        (c["id"], eval_sentences[s])
        for c in DEV
        for e in c["evidence"]
        if (s := evidence_sentence(e)) in eval_sentences
    ]
    assert not shared, shared


def test_dev_set_covers_the_categories_step3_will_tune_for():
    assert {"keyword", "paraphrase", "multi_doc", "area_hint", "current_version", "unanswerable"} <= {
        c["category"] for c in DEV
    }


def test_only_the_evaluation_harness_reads_the_evaluation_file():
    readers = {
        p.relative_to(ASSISTANT).as_posix()
        for p in ASSISTANT.rglob("*.py")
        if "retrieval_cases" in p.read_text() or "RETRIEVAL_CASES" in p.read_text()
    }
    assert readers <= {"frozen.py", "retrieval_eval.py", "generation_eval.py"}, readers


# ---------------- round 2 dev set (Step 3 round 2) ----------------

DEV2 = load(frozen.RETRIEVAL_DEV_ROUND2)


def test_round2_dev_is_round1_plus_ten_with_more_unanswerable_near_misses():
    assert DEV2[: len(DEV)] == DEV and len(DEV2) == len(DEV) + 10
    assert sum(not c["answerable"] for c in DEV2) == 10 and sum(c["answerable"] for c in DEV2) == 15


@pytest.mark.parametrize("case", DEV2[len(DEV) :], ids=lambda c: c["id"])
def test_round2_additions_follow_the_hit_rule(case):
    test_labels_follow_the_hit_rule(case)


def test_round2_dev_shares_no_question_or_evidence_sentence_with_eval():
    eval_sentences = {evidence_sentence(e) for c in EVAL for e in c["evidence"]}
    assert not {norm(c["question"]) for c in DEV2} & {norm(c["question"]) for c in EVAL}
    assert not [c["id"] for c in DEV2 for e in c["evidence"] if evidence_sentence(e) in eval_sentences]


@pytest.mark.parametrize("case", [c for c in DEV2[len(DEV) :] if not c["answerable"]], ids=lambda c: c["id"])
def test_round2_unanswerable_topics_are_absent(case):
    term = {
        "E04": r"valet",
        "E05": r"\bprice\b|telehealth visits? costs?",
        "E06": r"waiting room|child",
        "E07": r"per year",
        "E08": r"language",
        "E09": r"\bwait",
        "E10": r"insurance",
    }[case["id"]]
    assert not any(re.search(term, t, re.I) for t in TEXT.values())
