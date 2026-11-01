"""Guards the evaluation set frozen before any tuning (2026-11-01): the 18 cases and the six policies they
refer to are unchanged, the user-authored cases are marked, and no tuning code reads the evaluation file."""

import hashlib
import json
import re
from pathlib import Path

import pytest

from assistant import frozen

ASSISTANT = Path(frozen.__file__).resolve().parent
USER_AUTHORED = {"U1", "U2", "U3", "U4", "U5", "U6", "U7", "U8", "U9", "U9b", "A6", "N1"}
# Code that may read the evaluation cases: the freeze record itself and, from Step 12, the evaluation runner.
MAY_READ_EVAL = {ASSISTANT / "frozen.py", ASSISTANT / "evaluate.py"}


@pytest.fixture(scope="module")
def cases():
    return json.loads(frozen.EVAL_CASES.read_text())["cases"]


@pytest.mark.parametrize("relative", sorted(frozen.FROZEN_SHA256))
def test_frozen_file_is_unchanged(relative):
    assert hashlib.sha256((ASSISTANT / relative).read_bytes()).hexdigest() == frozen.FROZEN_SHA256[relative]


def test_every_policy_file_is_frozen():
    on_disk = {f"policies/{p.name}" for p in frozen.POLICY_DIR.glob("*.md")}
    assert on_disk == {k for k in frozen.FROZEN_SHA256 if k.startswith("policies/")}


def test_eighteen_cases_with_unique_ids(cases):
    ids = [c["id"] for c in cases]
    assert len(ids) == 18 and len(set(ids)) == 18


def test_user_authored_cases_are_marked(cases):
    assert {c["id"] for c in cases if c["author"] == "user"} == USER_AUTHORED


def test_brief_categories_are_covered(cases):
    categories = {c["category"] for c in cases}
    assert {"answerable", "ambiguous", "out_of_scope", "prompt_injection"} <= categories
    assert sum(c["category"] == "prompt_injection" for c in cases) >= 2


def test_every_expected_source_is_a_frozen_policy(cases):
    policies = {p.name for p in frozen.POLICY_DIR.glob("*.md")}
    for c in cases:
        for source in [c.get("expected_source"), c.get("if_answered", {}).get("expected_source")]:
            assert source is None or source in policies, c["id"]


def test_no_policy_covers_the_near_miss_case():
    """N1 asks about Sundays: no policy may mention weekend days."""
    for p in frozen.POLICY_DIR.glob("*.md"):
        assert not re.search(r"sunday|saturday|weekend", p.read_text(), re.I), p.name


def test_no_tuning_code_reads_the_evaluation_cases():
    offenders = [str(p.relative_to(ASSISTANT)) for p in ASSISTANT.rglob("*.py")
                 if p not in MAY_READ_EVAL and re.search(r"eval_cases|EVAL_CASES", p.read_text())]
    assert offenders == []
