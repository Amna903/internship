"""Week 4 Step 1 evidence (S1, S2): docs/SUPERVISED.md states exactly what the code and data do.

Each table in that page is parsed and compared with config, the feature code, the real split and the
real leakage scores, so the definitions can't drift from the pipeline."""

import re
from pathlib import Path

import pytest

from ml import config
from ml.data import generate
from ml.eda import LEAKAGE_AUC, single_feature_auc
from ml.features import ENGINEERED_NUMERIC
from ml.preprocess import ColumnGuard
from ml.split import split

DOC = Path(__file__).resolve().parents[2] / "docs" / "SUPERVISED.md"


@pytest.fixture(scope="module")
def df():
    return generate()


@pytest.fixture(scope="module")
def doc():
    return DOC.read_text()


def section(doc: str, heading: str) -> str:
    """Text from a '## heading' up to the next '## '."""
    match = re.search(rf"^## {re.escape(heading)}.*?$(.*?)(?=^## |\Z)", doc, re.M | re.S)
    assert match, f"missing section: {heading}"
    return match.group(1)


def tables(text: str) -> list[list[list[str]]]:
    """Every markdown table in the text, as rows of cells, header and separator rows dropped."""
    found, current = [], []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            current.append([c.strip() for c in line.strip("|").split("|")])
        elif current:
            found.append([r for r in current[2:]])
            current = []
    return found


def first_column(table) -> list[str]:
    return [r[0].strip("`") for r in table]


# ---------------- Definitions match the code ----------------


def test_feature_table_lists_exactly_the_configured_features_with_their_kind(doc):
    rows = tables(section(doc, "Features"))[0]
    kind = {f: "numeric" for f in config.NUMERIC_FEATURES}
    kind |= {f: "categorical" for f in config.CATEGORICAL_FEATURES}
    kind |= {f: "boolean" for f in config.BOOLEAN_FEATURES}
    assert first_column(rows) == config.FEATURES
    assert {r[0].strip("`"): r[1] for r in rows} == kind


def test_engineered_table_lists_exactly_the_engineered_features(doc):
    rows = tables(section(doc, "Features"))[1]
    assert first_column(rows) == ENGINEERED_NUMERIC


def test_never_features_are_exactly_ids_oracle_and_label_and_none_is_a_feature(doc):
    listed = first_column(tables(section(doc, "Never features"))[0])
    assert set(listed) == set(config.ID_COLUMNS + [config.ORACLE, config.LABEL])
    assert not set(listed) & set(config.FEATURES)


@pytest.mark.parametrize("forbidden", config.ID_COLUMNS + [config.ORACLE, config.LABEL])
def test_column_guard_rejects_every_never_feature(df, forbidden):
    with pytest.raises(ValueError):
        ColumnGuard().fit(df[config.FEATURES + [forbidden]])


def test_label_section_names_the_label_and_its_real_rate(doc, df):
    text = section(doc, "Label")
    assert f"`{config.LABEL}`" in text
    assert f"{100 * df[config.LABEL].mean():.1f}%" in text


def test_dataset_section_states_the_real_size_and_seed(doc, df):
    text = section(doc, "Dataset")
    assert f"{len(df):,} appointments" in text
    assert f"{df['patient_id'].nunique():,}" in text
    assert f"SEED = {config.SEED}" in text


# ---------------- Split ----------------


def test_split_table_matches_the_real_split(doc, df):
    rows = tables(section(doc, "Split strategy"))[0]
    for (name, rows_, patients, rate, _), part in zip(rows, split(df)):
        assert int(rows_.replace(",", "")) == len(part), name
        assert int(patients.replace(",", "")) == part["patient_id"].nunique(), name
        assert rate == f"{100 * part[config.LABEL].mean():.2f}%", name


def test_parts_have_similar_no_show_rates_as_the_doc_claims(df):
    rates = [p[config.LABEL].mean() for p in split(df)]
    assert max(rates) - min(rates) < 0.003


# ---------------- Leakage ----------------


def test_leakage_table_matches_the_real_single_feature_scores(doc, df):
    rows = tables(section(doc, "Leakage checks"))[1]
    scores = single_feature_auc(df)
    assert {r[0].strip("`"): r[1] for r in rows} == {f: f"{s:.3f}" for f, s in scores.items()}
    assert first_column(rows) == sorted(scores, key=scores.get, reverse=True)
    assert max(scores.values()) < LEAKAGE_AUC


def test_history_counts_only_include_earlier_appointments(df):
    """prior_no_shows must rise by exactly the previous appointment's outcome; if it included the
    current one, it would contain the label."""
    ordered = df.sort_values(["patient_id", "appointment_id"])
    by_patient = ordered.groupby("patient_id")
    no_show_step = by_patient["prior_no_shows"].diff().dropna()
    previous_outcome = by_patient[config.LABEL].shift().loc[no_show_step.index].astype(int)
    assert (no_show_step == previous_outcome).all()
    assert (by_patient["prior_appointments"].diff().dropna() == 1).all()


def test_history_check_would_catch_counts_that_include_the_current_outcome(df):
    leaky = df.assign(prior_no_shows=df["prior_no_shows"] + df[config.LABEL].astype(int))
    ordered = leaky.sort_values(["patient_id", "appointment_id"])
    by_patient = ordered.groupby("patient_id")
    step = by_patient["prior_no_shows"].diff().dropna()
    previous_outcome = by_patient[config.LABEL].shift().loc[step.index].astype(int)
    assert not (step == previous_outcome).all()
