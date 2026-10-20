"""Synthetic appointment dataset for an *educational* no-show model.

Nothing here is real. Rows are drawn from a hand-written generative process (below), so the
"true" drivers of a no-show are known: that is what lets us check the model learned something
sensible, and it is also the main limitation (the model can only learn our assumptions).
See docs/DATA_CARD.md.
"""

import hashlib

import numpy as np
import pandas as pd

from . import config

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
AGE_BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
VISIT_TYPES = ["in_person", "video", "phone"]
CHANNELS = ["web", "phone", "app"]
TRUTH_COLUMN = "_true_probability"

# Effects on the log-odds of a no-show. Planted on purpose; documented in the data card.
_AGE_EFFECT = {"18-24": 0.5, "25-34": 0.3, "35-44": 0.0, "45-54": -0.2, "55-64": -0.3, "65+": -0.1}
_VISIT_EFFECT = {"in_person": 0.0, "video": -0.3, "phone": -0.4}
_DAY_EFFECT = {"monday": 0.2, "friday": 0.25, "saturday": 0.1}
_CHANNEL_EFFECT = {"web": 0.1, "phone": -0.1, "app": 0.0}


def generate(n_rows: int = config.N_ROWS, n_patients: int = config.N_PATIENTS, seed: int = config.SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    patient = rng.integers(1, n_patients + 1, n_rows)
    # Age is a property of the patient, not the appointment (skewed younger: see "bias" in the data card).
    patient_age = rng.choice(AGE_BANDS, n_patients + 1, p=[0.16, 0.24, 0.22, 0.17, 0.13, 0.08])
    age_band = patient_age[patient]

    lead_time = np.minimum(rng.gamma(shape=1.6, scale=9.0, size=n_rows).round().astype(int), 180)
    weekday = rng.choice(WEEKDAYS, n_rows, p=[0.19, 0.19, 0.18, 0.18, 0.17, 0.09])
    hour = rng.integers(8, 19, n_rows)
    visit_type = rng.choice(VISIT_TYPES, n_rows, p=[0.6, 0.25, 0.15])
    channel = rng.choice(CHANNELS, n_rows, p=[0.45, 0.3, 0.25])
    reminder = rng.random(n_rows) < 0.7
    prior_appts = rng.poisson(4, n_rows)
    prior_ns = rng.binomial(prior_appts, rng.beta(1.2, 6, n_rows))
    distance = np.round(rng.lognormal(mean=2.0, sigma=0.8, size=n_rows), 1)

    ns_rate = np.where(prior_appts > 0, prior_ns / np.maximum(prior_appts, 1), 0.0)
    logit = (
        -2.2
        + 0.03 * np.minimum(lead_time, 60)
        - 0.8 * reminder
        + 2.0 * ns_rate
        + 0.4 * (prior_appts == 0)
        + np.vectorize(_AGE_EFFECT.get)(age_band)
        + np.vectorize(_VISIT_EFFECT.get)(visit_type)
        + np.vectorize(lambda d: _DAY_EFFECT.get(d, 0.0))(weekday)
        + np.vectorize(_CHANNEL_EFFECT.get)(channel)
        + np.where(hour < 9, 0.2, 0.0) + np.where(hour >= 17, 0.15, 0.0)
        + np.where(visit_type == "in_person", 0.012 * distance, 0.0)
        # Non-linear interaction a linear model can't express directly: long wait AND no reminder.
        + np.where((lead_time > 30) & ~reminder, 0.6, 0.0)
    )
    true_p = 1 / (1 + np.exp(-logit))
    no_show = rng.random(n_rows) < true_p

    # Missing values: distance not recorded for ~10% of bookings (missing completely at random).
    distance = np.where(rng.random(n_rows) < 0.10, np.nan, distance)

    df = pd.DataFrame(
        {
            "appointment_id": np.arange(1, n_rows + 1),
            "patient_ref": [f"P{p:05d}" for p in patient],
            "lead_time_days": lead_time,
            "appointment_weekday": weekday,
            "appointment_hour": hour,
            "age_band": age_band,
            "visit_type": visit_type,
            "booking_channel": channel,
            "reminder_sent": reminder,
            "prior_appointments": prior_appts,
            "prior_no_shows": prior_ns,
            "distance_km": distance,
            # LEAKY on purpose: only known *after* the appointment. Must never be a feature.
            "checked_in": ~no_show,
            config.TARGET: no_show.astype(int),
            # The generator's own probability. Kept in memory only to measure the best achievable score
            # (the "oracle" ceiling); never written to the CSV, never a feature.
            TRUTH_COLUMN: true_p,
        }
    )
    return df


def write(df: pd.DataFrame, path=config.DATA_PATH) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.drop(columns=[TRUTH_COLUMN], errors="ignore").to_csv(path, index=False)
    return file_sha256(path)


def file_sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
