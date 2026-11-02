"""Week 6 Step 5: every test file lands in exactly one CI group, and the RAG and model groups are not empty."""

from pathlib import Path

from tests.conftest import ci_group

FILES = sorted(p.name for p in Path(__file__).parent.glob("test_*.py"))


def test_rag_and_ml_groups_are_not_empty():
    groups = [ci_group(f) for f in FILES]
    assert groups.count("rag") >= 5 and groups.count("ml_pipeline") >= 5


def test_every_file_has_one_group():
    for f in FILES:
        assert ci_group(f) in ("rag", "ml_pipeline", None)
