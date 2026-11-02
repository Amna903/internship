"""Week 5 Step 5: the frozen follow-up conversations and history red-team set.

Guards the labels the same way as Step 2 (one-sentence quotes from the current edition, whole at every chunk
size) and the facts the user's choices rest on: the topic switches, the unanswerable follow-up, and that H2b
(not H2) is the case only the whole-conversation medical check can refuse."""

import json
import re
from pathlib import Path

import pytest

from assistant import frozen
from assistant.chunking import chunk, sentences
from assistant.privacy import redact
from assistant.verify import is_medical_advice_request

ASSISTANT = Path(frozen.__file__).resolve().parent
TEXT = {(n, v): (ASSISTANT / f).read_text() for n, v, f, _ in frozen.WEEK5_CORPUS_FILES}
CONV = json.loads(frozen.CONVERSATIONS.read_text())["cases"]
RED = json.loads(frozen.HISTORY_REDTEAM.read_text())


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def test_ten_conversations_five_by_the_user_two_topic_switches_one_unanswerable():
    assert len(CONV) == 10 and len({c["id"] for c in CONV}) == 10
    assert sum(c["author"] == "user" for c in CONV) == 5
    assert {c["id"] for c in CONV if c["category"] == "topic_switch"} == {"C5", "C10"}
    assert [c["id"] for c in CONV if not c["turns"][1]["answerable"]] == ["C8"]
    assert all(len(c["turns"]) == 2 for c in CONV)


@pytest.mark.parametrize("case", CONV, ids=lambda c: c["id"])
def test_every_quote_is_one_sentence_of_the_current_edition_and_whole_at_every_chunk_size(case):
    for t in case["turns"]:
        assert t["answerable"] == bool(t["evidence"])
        for e in t["evidence"]:
            assert frozen.WEEK5_CORPUS[e["document"]][0] == e["version"]
            text = TEXT[(e["document"], e["version"])]
            assert sum(norm(e["quote"]) in norm(s) for s in sentences(text)) == 1
            for size in range(20, 401, 20):
                assert any(norm(e["quote"]) in norm(ch) for ch in chunk(text, max_tokens=size)), size


@pytest.mark.parametrize("case", CONV, ids=lambda c: c["id"])
def test_answerable_follow_ups_have_a_key_and_the_unanswerable_one_has_none(case):
    assert (case["key"] is None) == (not case["turns"][1]["answerable"])


def test_c8_topic_is_absent_from_the_corpus():
    assert not any(re.search(r"electric|charging", t, re.I) for t in TEXT.values())


def test_h2b_turn_two_passes_alone_and_is_medical_only_in_context():
    h2, h2b = ({c["id"]: c for c in RED["live"]}[k]["turns"] for k in ("H2", "H2b"))
    assert is_medical_advice_request(h2[1])  # H2 alone doesn't need the whole-conversation check
    assert not is_medical_advice_request(h2b[1]) and is_medical_advice_request(" ".join(h2b))


def test_h3_number_is_redacted_but_the_name_is_not():
    text, n = redact({c["id"]: c for c in RED["live"]}["H3"]["turns"][0])
    assert n == 1 and "0300" not in text and "Ali Khan" in text  # names: the Week 4 known gap


def test_red_team_ids():
    assert [c["id"] for c in RED["live"]] == ["H1", "H2", "H2b", "H3", "H9"]
    assert [c["id"] for c in RED["offline"]] == ["H4", "H5", "H6", "H7", "H8"]
