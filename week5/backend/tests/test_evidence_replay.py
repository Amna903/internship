"""Week 4 review follow-up: every number in docs/evidence-replay.md still appears in the report it links to."""

import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"
ROW = re.compile(r"^\| (?P<claim>[^|]+) \| (?P<value>[^|]+) \| \[[^\]]+\]\((?P<link>[^)]+)\) \|", re.M)


def test_every_replayed_number_is_in_its_report():
    text = (DOCS / "evidence-replay.md").read_text()
    rows = ROW.findall(text)
    assert len(rows) >= 8
    for claim, value, link in rows:
        report = (DOCS / link).resolve().read_text()
        for number in re.findall(r"\d+\.\d+|\d+ / \d+", value):
            if "/" in number:
                a, b = (n.strip() for n in number.split("/"))
                assert re.search(rf"\b{a}\s*/\s*{b}\b|\b{a} of {b}\b", report), (claim, number, link)
            else:
                assert number in report, (claim, number, link)
