"""Week 4 review follow-up: the relevance development cases and the separate frozen relevance set.

The frozen set was committed before the relevance check existed; its hash is pinned, it shares no close copy
of a question with the dev cases or the original 18-case benchmark, and only the relevance runner reads it."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from assistant import frozen

ASSISTANT = Path(frozen.__file__).resolve().parent
DEV = ASSISTANT / "dev" / "relevance_dev.json"
MAX_WORD_OVERLAP = 0.5
MAY_READ_FROZEN = {"frozen.py", "relevance_eval.py"}


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def close(a: str, b: str) -> bool:
    x, y = words(a), words(b)
    return len(x & y) / len(x | y) >= MAX_WORD_OVERLAP


@pytest.fixture(scope="module")
def dev():
    return json.loads(DEV.read_text())["cases"]


@pytest.fixture(scope="module")
def held():
    return json.loads(frozen.RELEVANCE_FROZEN.read_text())["cases"]


def test_frozen_relevance_set_is_unchanged():
    assert hashlib.sha256(frozen.RELEVANCE_FROZEN.read_bytes()).hexdigest() == frozen.RELEVANCE_FROZEN_SHA256


def test_original_benchmark_record_is_untouched():
    assert "eval/relevance_frozen.json" not in frozen.FROZEN_SHA256 and len(frozen.FROZEN_SHA256) == 7


def test_sets_do_not_copy_each_other_or_the_benchmark(dev, held):
    bench = [c["question"] for c in json.loads(frozen.EVAL_CASES.read_text())["cases"]]
    for h in held:
        assert not any(close(h["question"], d["question"]) for d in dev), h["id"]
        assert not any(close(h["question"], b) for b in bench), h["id"]
    for d in dev:
        assert not any(close(d["question"], b) for b in bench), d["id"]


@pytest.mark.parametrize("name", ["dev", "held"])
def test_every_quote_is_real_policy_text_and_kinds_are_covered(name, request):
    cases = request.getfixturevalue(name)
    policies = " ".join(" ".join(p.read_text().lower().split()) for p in frozen.POLICY_DIR.glob("*.md"))
    for c in cases:
        assert all(" ".join(q.lower().split()) in policies for q in c["quotes"]), c["id"]
    assert {c["kind"] for c in cases} == {"off_topic_overlap", "on_topic", "reversal"}
    assert len({c["id"] for c in cases}) == len(cases)


def test_only_the_relevance_runner_reads_the_frozen_set():
    for py in ASSISTANT.rglob("*.py"):
        if py.name not in MAY_READ_FROZEN:
            assert "relevance_frozen" not in py.read_text() and "RELEVANCE_FROZEN" not in py.read_text(), py
