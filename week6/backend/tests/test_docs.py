"""The README's Week 3 numbers must equal the generated reports and the model metadata, and every local
link in the docs must point at a file that exists. Stops the documentation from going stale."""

import json
import re
from pathlib import Path

import pytest

from ml import config
from ml.inference import get_model

WEEK3 = Path(__file__).resolve().parents[2]
README = (WEEK3 / "README.md").read_text()
# Week 3 numbers describe the served release, so they are checked against its report.
METRICS = (WEEK3 / f"backend/ml/reports/release-{config.MODEL_VERSION}.md").read_text()
ERRORS = (WEEK3 / "backend/ml/reports/errors.md").read_text()
META = json.loads((WEEK3 / "backend/ml/artifacts/no-show-1.0.0.json").read_text())
WEEK3_SECTION = README.split("# Week 2: Role-Based")[0]


def metrics_test_row(prefix: str) -> list[str]:
    section = METRICS.split("## 4. Test set")[1].split("## 5.")[0]
    line = next(row for row in section.splitlines() if row.lstrip("| *").startswith(prefix))
    return [cell.strip(" *") for cell in line.strip("|").split("|")]


def readme_row(label: str) -> list[str]:
    metrics_section = WEEK3_SECTION.split("## Metrics")[1].split("## Dataset limitations")[0]
    line = next(
        row for row in metrics_section.splitlines() if row.startswith(f"| {label}") or row.startswith(f"| **{label}")
    )
    return [cell.strip(" *") for cell in line.strip("|").split("|")]


@pytest.mark.parametrize(
    "readme_label, report_prefix",
    [
        ("Floor", "floor"),
        ("Baseline", "baseline"),
        ("Gradient boosting", "best gradient boosting"),
        ("Served", "chosen"),
        ("Oracle ceiling", "oracle ceiling"),
    ],
)
def test_metrics_table_equals_the_generated_report(readme_label, report_prefix):
    report = metrics_test_row(report_prefix)
    readme = readme_row(readme_label)
    # report columns: model, PR-AUC, ROC-AUC, Brier, mean prediction, gap; README drops "mean prediction"
    assert readme[1:5] == [report[1], report[2], report[3], report[5]], (readme, report)


def test_bootstrap_interval_and_threshold_figures_match():
    difference, low, high = re.search(
        r"\*\*([+-]\d\.\d{3})\*\*, 95% interval\s*\*\*\[([+-]\d\.\d{3}), ([+-]\d\.\d{3})\]\*\*", METRICS
    ).groups()
    assert f"**{difference}**" in WEEK3_SECTION and f"**[{low}, {high}]**" in WEEK3_SECTION
    assert f"**Decision cut-off: {100 * META['decision']['threshold']:.1f}%**" in WEEK3_SECTION
    assert f"**{100 * META['metrics']['test_threshold']['recall']:.1f}%** of the no-shows" in WEEK3_SECTION
    assert f"**{100 * META['metrics']['test_threshold']['precision']:.1f}%** of the flagged" in WEEK3_SECTION
    flagged = re.search(r"\| test \(same threshold, applied once\) \|.*\| (\d+\.\d)% \|", METRICS).group(1)
    assert f"flags {flagged}% of" in WEEK3_SECTION


def test_calibration_and_bias_figures_match():
    ece = re.search(r"Expected calibration error.*\*\*(\d+\.\d+) points\*\*", ERRORS).group(1)
    assert f"error {ece} points" in WEEK3_SECTION
    young, old = re.search(
        r"\| false-positive rate \(attenders flagged\) \| (\d+\.\d)% \| (\d+\.\d)% \|", ERRORS
    ).groups()
    assert f"{young}% of 18–24-year-olds" in WEEK3_SECTION and f"against {old}% of 55–64" in WEEK3_SECTION
    with_age, without = re.search(r"PR-AUC (\d\.\d{3}) → (\d\.\d{3})", ERRORS).groups()
    assert f"PR-AUC {with_age} → {without}" in WEEK3_SECTION


def test_sample_response_is_what_the_model_returns():
    sample = json.loads(re.search(r"-d '(\{\"lead_time_days\".*?\})' http", WEEK3_SECTION).group(1))
    prediction = get_model().predict([sample])[0]
    for key, value in prediction.items():
        assert f'"{key}": {json.dumps(value)}' in WEEK3_SECTION, key
    assert config.DISCLAIMER in WEEK3_SECTION
    assert f'"model_version": "{META["model"]}"' in WEEK3_SECTION


def test_history_counts_note_is_present():
    assert "The caller supplies the appointment history counts; the API does not look them up." in WEEK3_SECTION


DOCS = [
    WEEK3 / "README.md",
    *sorted((WEEK3 / "docs").glob("*.md")),
    *sorted((WEEK3 / "backend/ml/reports").glob("*.md")),
]


@pytest.mark.parametrize("doc", DOCS, ids=[str(d.relative_to(WEEK3)) for d in DOCS])
def test_every_local_link_points_at_an_existing_file(doc):
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", doc.read_text()):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = (doc.parent / target.split("#")[0]).resolve()
        if not path.exists():
            broken.append(target)
    assert not broken, broken
