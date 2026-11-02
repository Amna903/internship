"""A fresh holdout, RESERVED (2026-11-01, mentor review on PR #1) for the next final evaluation only.

Why: the main dataset's test set was scored in Week 3 and then informed the Week 4 release decision, so it
can no longer give a clean estimate. This holdout is a separate synthetic dataset:
  - drawn with a different seed (HOLDOUT_SEED), so none of its outcomes were ever seen;
  - with patient and appointment IDs shifted into their own range (ID_OFFSET), so no ID can collide with
    the main dataset and a patient can never be in both;
  - pinned by its SHA-256, so it can't change silently.

Rules (guarded by tests/test_holdout.py):
  - It is never used for exploration, tuning, model choice or release selection. Only this module may
    load it; no other module in ml/ or the API imports it.
  - It is scored once, in the next final evaluation, for the model decided beforehand by the frozen
    champion/challenger rule (ml/release_rule.py). The result is reported, never used to choose.
Until then nothing reads its labels: the tests check its seed, IDs and fingerprint only.
"""

import pandas as pd

from . import config
from .data import dataset_hash, generate

HOLDOUT_SEED = 20261101  # not config.SEED (42)
N_PATIENTS = 2_000
ID_OFFSET = 10_000_000  # main dataset IDs are 1..~20,000; holdout IDs start above 10 million
# Fingerprint of the reserved data (canonical CSV, as for the main dataset). A changed generator or seed
# changes it, and a test fails, so the reserved data can't drift without anyone noticing.
HOLDOUT_SHA256 = "ee7f5ff44cb81f0618c7202b7b6ae98fc1897e7bd7b27b544733891a0d57cae7"


def load_holdout() -> pd.DataFrame:
    """The reserved holdout. Call only from the next final evaluation."""
    df = generate(seed=HOLDOUT_SEED, n_patients=N_PATIENTS)
    return df.assign(patient_id=df["patient_id"] + ID_OFFSET, appointment_id=df["appointment_id"] + ID_OFFSET)


def fingerprint() -> str:
    return dataset_hash(load_holdout())


assert HOLDOUT_SEED != config.SEED
